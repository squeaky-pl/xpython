import gccjit
import dis


def get_fun_code(source):
    module = compile(source, 'unknown', 'exec')
    return module.co_consts[0]


block_boundaries = [
    'RETURN_VALUE', 'POP_JUMP_IF_FALSE', 'SETUP_LOOP', 'JUMP_ABSOLUTE',
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

        assert 0, "Dont know what to do with {}".format(self)


class Compiler:
    def __init__(self, context, name, code):
        self.context = context
        self.name = name
        self.code = code
        self.stack = []

    def setup_function(self):
        code = self.code
        self.variables = []
        params = []

        # setup parameters
        for i in range(code.co_argcount):
            self.variables.append(Param(int, code.co_varnames[i]))
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
        stack = self.stack
        block_stack = self.block_stack
        block_map = self.block_map
        variables = self.variables
        context = self.context
        for instruction in dis.get_instructions(self.code):
            block = self.block
            opname = instruction.opname
            argval = instruction.argval
            arg = instruction.arg
            if opname == 'LOAD_CONST':
                self.load_const(instruction)
            elif opname == 'STORE_FAST':
                self.store_fast(instruction)
            elif opname == 'LOAD_FAST':
                self.load_fast(instruction)
            elif opname == 'BINARY_ADD':
                self.binary_add(instruction)
            elif opname == 'INPLACE_ADD':
                self.inplace_add(instruction)
            elif opname == 'COMPARE_OP':
                self.compare_op(instruction)
            elif opname == 'RETURN_VALUE':
                self.return_value(instruction)
            elif opname == 'POP_JUMP_IF_FALSE':
                self.pop_jump_if_false(instruction)
            # elif opname == 'JUMP_ABSOLUTE':
            #     block.end_with_jump(block_map[arg])
            #     self.block = next(self.block_iter)
            # elif opname == 'BREAK_LOOP':
            #     block.end_with_jump(block_stack[-1])
            #     self.block = next(self.block_iter)
            # elif opname == 'SETUP_LOOP':
            #     block_stack.append(block_map[instruction.offset + arg])
            #     next_block = next(self.block_iter)
            #     block.end_with_jump(next_block)
            #     self.block = next_block
            # elif opname == 'POP_BLOCK':
            #     block_stack.pop()
            else:
                assert 0, "Unknown opname " + opname

            print('stack {}'.format(stack))

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

    def return_value(self, instruction):
        self.block.end_with_return(self.stack.pop().tojit(self.context))
        self.block = next(self.block_iter, None)

    def pop_jump_if_false(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_conditonal(
            self.stack.pop().tojit(self.context),
            next_block, self.block_map[instruction.arg])
        self.block = next_block


def compile_to_context(context, name, code):
    compiler = Compiler(context, name, code)
    compiler.setup_function()
    compiler.setup_blocks()
    compiler.compile()
