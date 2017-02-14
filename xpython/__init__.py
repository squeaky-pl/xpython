import gccjit
import dis


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
    def __init__(self, value):
        self.value = value
        super().__init__(type(value))

    def _tojit(self, context):
        if self.typ is int:
            return context.integer(self.value)

        assert 0, "Dont know what to do with {}".format(self.value)


class Local(Rvalue):
    def __init__(self, function, typ, name):
        self.name = name
        self.function = function
        super().__init__(typ)

    def _tojit(self, context):
        if self.typ is int:
            return context.local(self.function, "int", self.name)

        assert 0, "Dont know what to do with {}".format(self)


class Param(Rvalue):
    def __init__(self, typ, name):
        self.name = name
        super().__init__(typ)

    def _tojit(self, context):
        if self.typ is int:
            return context.param("int", self.name)
        elif self.typ is bytearray:
            char_p = context.pointer_type("char")
            return context.param(char_p, self.name)

        assert 0, "Dont know what to do with {}".format(self)


class Compiler:
    def __init__(self, context, name, code, param_types):
        self.context = context
        self.name = name
        self.code = code
        self.param_types = param_types
        self.stack = []


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

    def setup_blocks(self):
        blocks = []
        self.block_map = {}
        current_block_pos = None
        for instruction in dis.get_instructions(self.code):
            if current_block_pos is None:
                current_block_pos = instruction.offset
            if instruction.opname in block_boundaries:
                block = self.context.block(self.function)
                blocks.append(block)
                self.block_map[current_block_pos] = block
                current_block_pos = None

        print(self.block_map)

        self.block_iter = iter(blocks)
        self.block = next(self.block_iter)
        self.block_stack = []

    def compile(self):
        for instruction in dis.get_instructions(self.code):
            try:
                handler = getattr(self, instruction.opname.lower())
            except AttributeError:
                assert 0, "Unknown opname " + instruction.opname

            handler(instruction)

            print('stack {}'.format(self.stack))

    def load_const(self, instruction):
        self.stack.append(Constant(instruction.argval))

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

        assert index.typ is int, "index must be int"
        assert where.typ is bytearray, "where must be bytearray"
        assert what.typ is int, "what must be int"

        lvalue = self.context.array_access(
            where.tojit(self.context), index.tojit(self.context))

        narrow_cast = self.context.cast(what.tojit(self.context), "char")

        self.block.add_assignment(lvalue, narrow_cast)

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
        self.block_stack.pop()

def compile_to_context(context, name, code, param_types):
    compiler = Compiler(context, name, code, param_types)
    compiler.setup_function()
    compiler.setup_blocks()
    compiler.compile()
