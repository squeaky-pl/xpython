from collections import OrderedDict
import gccjit
import dis
from cffi import FFI


ffi = FFI()
ffi.cdef("""
typedef struct {
    unsigned long size;
    char* data;
} buffer;

typedef struct {
    unsigned long size;
    const char* data;
} ibuffer;
""")


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


class Rvalue:
    def __init__(self, typ, _jit=None):
        self.typ = typ
        self._jit = _jit

    def tojit(self, context):
        if not self._jit:
            self._jit = self._tojit(context)

        return self._jit


class Constant(Rvalue):
    def __init__(self, typ, value):
        self.value = value
        super().__init__(typ)

    def _tojit(self, context):
        if self.typ is int:
            return context.integer(self.value)
        elif self.typ == 'unsigned':
            return context.integer(self.value, 'unsigned long')
        elif self.typ == 'byte':
            return context.integer(self.value, 'char')

        assert 0, "Dont know what to do with {}".format(self.value)


class Global:
    def __init__(self, name):
        self.name = name


class Unreachable:
    pass


class Local(Rvalue):
    def __init__(self, function, typ, name):
        self.name = name
        self.function = function
        super().__init__(typ)

    def _tojit(self, context):
        if self.typ is int:
            return context.local(self.function, "int", self.name)
        elif self.typ == 'unsigned':
            return context.local(self.function, "unsigned long", self.name)

        assert 0, "Dont know what to do with {}".format(self)


class Param(Rvalue):
    def __init__(self, typ, name):
        self.name = name
        super().__init__(typ)

    def _tojit(self, context):
        if self.typ is int:
            return context.param("int", self.name)
        elif self.typ == 'unsigned':
            return context.param("unsigned long", self.name)
        elif self.typ == 'buffer':
            # TODO FIXME to jit should depend on compiler?
            return context.param(context.buffer_p_type, self.name)

        assert 0, "Dont know what to do with {}".format(self)


class Compiler:
    def __init__(self, context, name, code, param_types):
        self.context = context
        self.name = name
        self.code = code
        self.param_types = param_types
        self.stack = []

    def setup_common(self):
        char_p = self.context.pointer_type("char")
        self.size_field = self.context.field("unsigned long", "size")
        self.data_field = self.context.field(char_p, "data")
        self.buffer_type = self.context.struct_type(
            "buffer", [self.size_field, self.data_field])
        self.buffer_p_type = self.context.pointer_type(self.buffer_type)
        # TODO FIXME to jit should depend on compiler?
        self.context.buffer_p_type = self.buffer_p_type

        __builtin_trap = self.context.builtin_function("__builtin_trap")

        # bound check code
        buffer_param = self.context.param(self.buffer_p_type, "buffer")
        index_param = self.context.param("unsigned long", "index")
        self.bound_check = self.context.internal_function(
             "void", "bound_check", [buffer_param, index_param])

        cmp_block = self.context.block(self.bound_check)
        trap_block = self.context.block(self.bound_check)
        ret_block = self.context.block(self.bound_check)

        size = self.context.dereference_field(buffer_param, self.size_field)
        comparison = self.context.comparison('<', index_param, size)
        cmp_block.end_with_conditonal(comparison, ret_block, trap_block)

        trap_call = self.context.call(__builtin_trap)
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
            "int", self.name, params)

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

    def compile(self):
        for instruction in dis.get_instructions(self.code):
            try:
                handler = getattr(self, instruction.opname.lower())
            except AttributeError:
                assert 0, "Unknown opname " + instruction.opname

            handler(instruction)

            print('block {}, stack {}'.format(self.block, self.stack))

    def load_const(self, instruction):
        self.stack.append(Constant(int, instruction.argval))

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

    def load_fast(self, instruction):
        self.stack.append(self.variables[instruction.arg])

    def binary_add(self, instruction):
        addition = self.context.binary(
            '+', "int",
            self.stack.pop().tojit(self.context),
            self.stack.pop().tojit(self.context))
        self.stack.append(Rvalue(int, addition))

    def inplace_add(self, instruction):
        b = self.stack.pop()
        a = self.stack.pop()
        addition = self.context.binary(
            '+', "int",
            a.tojit(self.context),
            b.tojit(self.context))
        self.stack.append(Rvalue(int, addition))

    def compare_op(self, instruction):
        b = self.stack.pop()
        a = self.stack.pop()
        comparison = self.context.comparison(
            dis.cmp_op[instruction.arg],
            a.tojit(self.context),
            b.tojit(self.context))
        self.stack.append(Rvalue(int, comparison))

    def store_subscr(self, instruction):
        index = self.stack.pop()
        where = self.stack.pop()
        what = self.stack.pop()

        assert index.typ in (int, "unsigned"), "index must be integer"
        assert where.typ == 'buffer', "where must be buffer"
        assert what.typ == 'byte', "what must be byte"

        data = self.context.dereference_field(
            where.tojit(self.context), self.data_field)

        bound_check_call = self.context.call(
            self.bound_check,
            [where.tojit(self.context), index.tojit(self.context)])
        self.block.add_eval(bound_check_call)

        lvalue = self.context.array_access(
            data, index.tojit(self.context))

        self.block.add_assignment(lvalue, what.tojit(self.context))

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

        assert 0, "Don't know what to do with {}({})".format(
            function, arguments)

    def return_value(self, instruction):
        self.block.end_with_return(self.stack.pop().tojit(self.context))
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

def compile_to_context(context, name, code, param_types):
    compiler = Compiler(context, name, code, param_types)
    compiler.setup_common()
    compiler.setup_function()
    compiler.setup_blocks()
    compiler.compile()
