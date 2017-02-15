from collections import OrderedDict
import gccjit
import dis
from cffi import FFI


xtype_to_c = {
    int: "int",
    "byte": "char",
    "unsigned": "unsigned long",
    "signed": "signed long",
    "void": "void"
}


DEFAULT_INTEGER_TYPE = int
DEFAULT_INTEGER_CTYPE = xtype_to_c[DEFAULT_INTEGER_TYPE]
BOUND_CHECKS = True

ffi = FFI()
ffi.cdef("""
typedef struct {{
    {ctype} size;
    char* data;
}} buffer;

typedef struct {{
    {ctype} size;
    const char* data;
}} ibuffer;
""".format(ctype=DEFAULT_INTEGER_CTYPE))


def xtypeasc(typ):
    return xtype_to_c[typ]


class Buffer:
    def __init__(self, data):
        self._data = ffi.new("char[]", data)
        self._ffi = ffi.new("buffer*")
        self._ffi.size = self.size
        self._ffi.data = self._data

    @property
    def data(self):
        return ffi.unpack(self._data, self.size)

    @property
    def size(self):
        return len(self._data) - 1

    @property
    def ffi(self):
        return self._ffi


def get_fun_code(source):
    module = compile(source, 'unknown', 'exec')
    return module.co_consts[0]


block_boundaries = [
    'RETURN_VALUE', 'POP_JUMP_IF_FALSE', 'POP_JUMP_IF_TRUE', 'SETUP_LOOP', 'JUMP_ABSOLUTE',
    'BREAK_LOOP'
]


def type_repr(typ):
    if isinstance(typ, tuple):
        return '({})'.format(', '.join(type_repr(t) for t in typ))
    elif isinstance(typ, str):
        return typ
    else:
        return typ.__name__


class Rvalue:
    def __init__(self, typ, desc=None, _jit=None):
        self.typ = typ
        self._jit = _jit
        self.desc = desc

    def tojit(self, context):
        if not self._jit:
            self._jit = self._tojit(context)

        return self._jit

    def __repr__(self):
        return '<Rvalue {}: {}>'.format(self.desc or '', type_repr(self.typ))


class Constant(Rvalue):
    def __init__(self, typ, value):
        self.value = value
        super().__init__(typ)

    @classmethod
    def frompy(cls, value):
        if value is None:
            return None
        elif isinstance(value, tuple):
            return cls(tuple(type(i) for i in value), value)
        elif isinstance(value, DEFAULT_INTEGER_TYPE):
            return cls(DEFAULT_INTEGER_TYPE, value)

        assert 0

    def __repr__(self):
        return '<Constant {}: {}>'.format(self.value, type_repr(self.typ))

    def _tojit(self, context):
        return context.integer(self.value, xtypeasc(self.typ))


class Global:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<Global {}>'.format(self.name)


class Unreachable:
    pass


class Local(Rvalue):
    def __init__(self, function, typ, name):
        self.function = function
        super().__init__(typ, name)

    def __repr__(self):
        return '<Local {}: {} @{:x}>'.format(
            self.desc, type_repr(self.typ), id(self))

    def _tojit(self, context):
        return context.local(self.function, xtypeasc(self.typ), self.desc)


class Temporary(Local):
    def __init__(self, function, typ, idx, src):
        self.src = src
        super().__init__(function, typ, '@' + str(idx))

    def __repr__(self):
        return '<Temporary {}: {} from {}>'.format(
            self.desc, type_repr(self.typ), self.src.desc)


class Param(Rvalue):
    def __init__(self, typ, name):
        super().__init__(typ, name)

    def _tojit(self, context):
        if self.typ == 'buffer':
            ctyp = context.buffer_p_type
        else:
            ctyp = xtypeasc(self.typ)

        return context.param(ctyp, self.desc)


class Compiler:
    def __init__(self, context, code, ret_type, name, param_types):
        self.context = context
        self.code = code
        self.ret_type = ret_type
        self.name = name
        self.param_types = param_types
        self.stack = []
        self.temporaries = 0

    def setup_common(self):
        char_p = self.context.pointer_type("char")
        self.size_field = self.context.field(DEFAULT_INTEGER_CTYPE, "size")
        self.data_field = self.context.field(char_p, "data")
        self.buffer_type = self.context.struct_type(
            "buffer", [self.size_field, self.data_field])
        self.buffer_p_type = self.context.pointer_type(self.buffer_type)
        # TODO FIXME to jit should depend on compiler?
        self.context.buffer_p_type = self.buffer_p_type

        if BOUND_CHECKS:
            abort = self.context.imported_function("void", "abort")

            # bound check code
            buffer_param = self.context.param(self.buffer_p_type, "buffer")
            index_param = self.context.param(DEFAULT_INTEGER_CTYPE, "index")
            self.bound_check = self.context.internal_function(
                 "void", "bound_check", [buffer_param, index_param])

            cmp_block = self.context.block(self.bound_check)
            trap_block = self.context.block(self.bound_check)
            ret_block = self.context.block(self.bound_check)

            size = self.context.dereference_field(buffer_param, self.size_field)
            comparison = self.context.comparison('<', index_param, size)
            cmp_block.end_with_conditonal(comparison, ret_block, trap_block)

            trap_call = self.context.call(abort)
            trap_block.add_eval(trap_call)
            trap_block.end_with_void_return()

            ret_block.end_with_void_return()

    def setup_function(self):
        code = self.code
        self.variables = []
        params = []

        # setup parameters
        for i in range(code.co_argcount):
            self.variables.append(
                Param(self.param_types[i], code.co_varnames[i]))
            params = [v.tojit(self.context) for v in self.variables]

        self.function = self.context.exported_function(
            xtypeasc(self.ret_type), self.name, params)

        # setup locals
        for i in range(code.co_argcount, code.co_nlocals):
            self.variables.append(
                Local(self.function, None, code.co_varnames[i]))

    def make_block(self, instruction):
        return self.context.block(
            self.function, '{0.offset} {0.opname}'.format(instruction))

    def setup_blocks(self):
        self.block_map = OrderedDict()

        instructions = OrderedDict(
            (i.offset, i) for i in dis.get_instructions(self.code))

        block = self.make_block(instructions[0])
        self.block_map[0] = block

        for instruction in instructions.values():
            if instruction.offset in self.block_map:
                continue

            if instruction.is_jump_target:
                block = self.make_block(instruction)
                self.block_map[instruction.offset] = block
                continue

            if instruction.opname in block_boundaries:
                offset = instruction.offset + 2
                # check if this is the last instruction
                if offset == len(self.code.co_code):
                    break

                block = self.make_block(instructions[offset])
                self.block_map[offset] = block

        print(self.block_map)

        self.block_iter = iter(self.block_map.values())
        self.block = next(self.block_iter)
        self.block_stack = []

    def emit(self):
        for instruction in dis.get_instructions(self.code):
            print('block {}, stack {}'.format(self.block, self.stack))

            try:
                handler = getattr(self, instruction.opname.lower())
            except AttributeError:
                assert 0, "Unknown opname " + instruction.opname

            handler(instruction)

    def load_const(self, instruction):
        self.stack.append(Constant.frompy(instruction.argval))

    def load_global(self, instruction):
        self.stack.append(Global(instruction.argval))

    def store_fast(self, instruction):
        variable = self.variables[instruction.arg]
        a = self.stack.pop()
        if not variable.typ:
            variable.typ = a.typ

        self.block.add_assignment(
            variable.tojit(self.context),
            a.tojit(self.context))

    def temporary(self, src):
        tmp = Temporary(self.function, src.typ, self.temporaries, src)
        self.temporaries += 1
        return tmp

    def load_fast(self, instruction):
        var = self.variables[instruction.arg]

        # FIXME, not all types need temporary, e.g. buffer
        if var.typ != 'buffer':
            tmp = self.temporary(var)

            self.block.add_assignment(
                tmp.tojit(self.context),
                var.tojit(self.context))

            push = tmp
        else:
            push = var

        self.stack.append(push)

    def binary_add(self, instruction):
        addition = self.context.binary(
            '+', xtypeasc(DEFAULT_INTEGER_TYPE),
            self.stack.pop().tojit(self.context),
            self.stack.pop().tojit(self.context))
        self.stack.append(Rvalue(DEFAULT_INTEGER_TYPE, '+', addition))

    def binary_subtract(self, instruction):
        b = self.stack.pop()
        a = self.stack.pop()
        substraction = self.context.binary(
            '-', xtypeasc(DEFAULT_INTEGER_TYPE),
            a.tojit(self.context),
            b.tojit(self.context))
        self.stack.append(Rvalue(DEFAULT_INTEGER_TYPE, '-', substraction))

    def binary_floor_divide(self, instruction):
        # FIXME: this only works for positive numbers!
        # http://stackoverflow.com/questions/828092/python-style-integer-division-modulus-in-c
        b = self.stack.pop()
        a = self.stack.pop()
        division = self.context.binary(
            '/', xtypeasc(DEFAULT_INTEGER_TYPE),
            a.tojit(self.context),
            b.tojit(self.context))
        self.stack.append(Rvalue(DEFAULT_INTEGER_TYPE, '//', division))

    def inplace_add(self, instruction):
        b = self.stack.pop()
        a = self.stack.pop()
        addition = self.context.binary(
            '+', xtypeasc(DEFAULT_INTEGER_TYPE),
            a.tojit(self.context),
            b.tojit(self.context))
        self.stack.append(Rvalue(DEFAULT_INTEGER_TYPE, '+', addition))

    def compare_op(self, instruction):
        b = self.stack.pop()
        a = self.stack.pop()
        comparison = self.context.comparison(
            dis.cmp_op[instruction.arg],
            a.tojit(self.context),
            b.tojit(self.context))
        self.stack.append(Rvalue(int, 'comp', comparison))

    def unpack_sequence(self, instruction):
        arg = self.stack.pop()
        for item in reversed(arg.value):
            self.stack.append(Constant.frompy(item))

    def rot_two(self, instruction):
        stack = self.stack
        stack[-1], stack[-2] = stack[-2], stack[-1]

    def rot_three(self, instruction):
        stack = self.stack
        stack[-1], stack[-2], stack[-3] = stack[-2], stack[-3], stack[-1]

    def store_subscr(self, instruction):
        index = self.stack.pop()
        where = self.stack.pop()
        what = self.stack.pop()

        assert index.typ in (int, "unsigned"), "index must be integer"
        assert where.typ == 'buffer', "where must be buffer"
        assert what.typ == 'byte', "what must be byte"

        data = self.context.dereference_field(
            where.tojit(self.context), self.data_field)

        if BOUND_CHECKS:
            bound_check_call = self.context.call(
                self.bound_check,
                [where.tojit(self.context), index.tojit(self.context)])
            self.block.add_eval(bound_check_call)

        lvalue = self.context.array_access(
            data, index.tojit(self.context))

        self.block.add_assignment(lvalue, what.tojit(self.context))

    def binary_subscr(self, instruction):
        index = self.stack.pop()
        where = self.stack.pop()

        assert index.typ in (int, "unsigned"), "index must be integer"
        assert where.typ == 'buffer', "where must be buffer"

        data = self.context.dereference_field(
            where.tojit(self.context), self.data_field)

        if BOUND_CHECKS:
            bound_check_call = self.context.call(
                self.bound_check,
                [where.tojit(self.context), index.tojit(self.context)])
            self.block.add_eval(bound_check_call)

        rvalue = Rvalue(
            "byte", "[]",
            self.context.array_access(data, index.tojit(self.context)))

        tmp = self.temporary(rvalue)

        self.block.add_assignment(
            tmp.tojit(self.context),
            rvalue.tojit(self.context))

        self.stack.append(tmp)

    def call_function(self, instruction):
        arguments = []
        for _ in range(instruction.arg):
            arguments.append(self.stack.pop())
        function = self.stack.pop()

        if isinstance(function, Global):
            if function.name == 'abort' and instruction.arg == 0:
                __builtin_trap = self.context.builtin_function('__builtin_trap')
                trap_call = self.context.call(__builtin_trap)
                self.block.add_eval(trap_call)
                self.stack.append(Unreachable())

                return

            if function.name == 'byte' and instruction.arg == 1:
                rvalue = arguments[0]

                if isinstance(rvalue, Constant):
                    if 0 <= rvalue.value <= 0xff:
                        self.stack.append(Constant('byte', rvalue.value))
                    else:
                        assert 0, "Constant out of bounds for byte"

                    return

            if function.name == 'len' and instruction.arg == 1:
                rvalue = arguments[0]

                if isinstance(rvalue, Rvalue) and rvalue.typ == 'buffer':
                    size = self.context.dereference_field(
                        rvalue.tojit(self.context), self.size_field)

                    self.stack.append(Rvalue(DEFAULT_INTEGER_TYPE, "size", size))

                    return

        assert 0, "Don't know what to do with {}({})".format(
            function, arguments)

    def return_value(self, instruction):
        retval = self.stack.pop()
        if self.ret_type != 'void':
            self.block.end_with_return(retval.tojit(self.context))
        else:
            self.block.end_with_void_return()

        self.block = next(self.block_iter, None)

    def pop_jump_if_false(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_conditonal(
            self.stack.pop().tojit(self.context),
            next_block, self.block_map[instruction.arg])
        self.block = next_block

    def pop_jump_if_true(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_conditonal(
            self.stack.pop().tojit(self.context),
            self.block_map[instruction.arg], next_block)
        self.block = next_block

    def pop_top(self, instruction):
        top = self.stack.pop()

        if isinstance(top, Unreachable):
            next_block = next(self.block_iter)
            self.block.end_with_jump(next_block)
            self.block = next_block
        else:
            assert 0, "Dont know how to handle {}".format(top)

    def jump_absolute(self, instruction):
        self.block.end_with_jump(self.block_map[instruction.arg])
        self.block = next(self.block_iter)

    def break_loop(self, instruction):
        self.block.end_with_jump(self.block_stack[-1])
        self.block = next(self.block_iter)

    def setup_loop(self, instruction):
        self.block_stack.append(
            self.block_map[instruction.offset + instruction.arg])
        next_block = next(self.block_iter)
        self.block.end_with_jump(next_block)
        self.block = next_block

    def pop_block(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_jump(next_block)
        self.block = next_block
        self.block_stack.pop()

    def compile(self):
        return CompilerResult(self, self.context.compile())


class CompilerResult:
    def __init__(self, compiler, result):
        self.compiler = compiler
        self.result = result

    def code(self, name):
        return self.result.code(name)

    def cffi(self, name):
        compiler = self.compiler
        code = self.result.code(name)

        cparams = ','.join(xtypeasc(p) for p in compiler.param_types)
        cdef = xtypeasc(compiler.ret_type) + "(*)(" + cparams + ")"

        return ffi.cast(cdef, code)


def compile_one(context, code, ret_type, name, param_types):
    compiler = Compiler(context, code, ret_type, name, param_types)
    compiler.setup_common()
    compiler.setup_function()
    compiler.setup_blocks()
    compiler.emit()
    return compiler.compile()
