import gccjit
import dis


def get_fun_code(source):
    module = compile(source, 'unknown', 'exec')
    return module.co_consts[0]


block_boundaries = [
    'RETURN_VALUE', 'POP_JUMP_IF_FALSE', 'SETUP_LOOP', 'JUMP_ABSOLUTE',
    'BREAK_LOOP'
]


class Compiler:
    def __init__(self, context, name, code):
        self.context = context
        self.name = name
        self.code = code
        self.stack = []

    def setup_function(self):
        code = self.code
        self.variables = []

        # setup parameters
        for i in range(code.co_argcount):
            self.variables.append(
                self.context.param("int", code.co_varnames[i]))

        self.function = self.context.exported_function(
            "int", self.name, self.variables)

        # setup locals
        for i in range(code.co_argcount, code.co_nlocals):
            self.variables.append(
                self.context.local(self.function, "int", code.co_varnames[i]))

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
                load_const(context, stack, argval)
            elif opname == 'STORE_FAST':
                block.add_assignment(variables[arg], stack.pop())
            elif opname == 'LOAD_FAST':
                stack.append(variables[arg])
            elif opname == 'BINARY_ADD':
                # stack.append(stack.pop() + stack.pop())
                addition = context.binary('+', "int", stack.pop(), stack.pop())
                stack.append(addition)
            elif opname == 'INPLACE_ADD':
                b = stack.pop()
                a = stack.pop()
                addition = context.binary('+', "int", a, b)
                stack.append(addition)
            elif opname == 'COMPARE_OP':
                b = stack.pop()
                a = stack.pop()
                comparison = context.comparison(dis.cmp_op[arg], a, b)
                stack.append(comparison)
            elif opname == 'RETURN_VALUE':
                block.end_with_return(stack.pop())
                self.block = next(self.block_iter, None)
                # ret = stack.pop()
            elif opname == 'POP_JUMP_IF_FALSE':
                next_block = next(self.block_iter)
                block.end_with_conditonal(stack.pop(), next_block, block_map[arg])
                self.block = next_block
            elif opname == 'JUMP_ABSOLUTE':
                block.end_with_jump(block_map[arg])
                self.block = next(self.block_iter)
            elif opname == 'BREAK_LOOP':
                block.end_with_jump(block_stack[-1])
                self.block = next(self.block_iter)
            elif opname == 'SETUP_LOOP':
                block_stack.append(block_map[instruction.offset + arg])
                next_block = next(self.block_iter)
                block.end_with_jump(next_block)
                self.block = next_block
            elif opname == 'POP_BLOCK':
                block_stack.pop()
            else:
                assert 0, "Unknown opname " + opname

            print('stack {}'.format(stack))


def compile_to_context(context, name, code):
    compiler = Compiler(context, name, code)
    compiler.setup_function()
    compiler.setup_blocks()
    compiler.compile()


def load_const(context, stack, argval):
    if isinstance(argval, int):
        value = context.integer(argval)
    else:
        assert 0, "Dont know what to do with {}".format(argval)
    stack.append(value)
