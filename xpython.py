import gccjit
import dis


def get_fun_code(source):
    module = compile(source, 'unknown', 'exec')
    return module.co_consts[0]


block_boundaries = [
    'RETURN_VALUE', 'POP_JUMP_IF_FALSE', 'SETUP_LOOP', 'JUMP_ABSOLUTE'
]


def compile_to_context(context, name, code):
    stack = []
    variables = []
    ret = ...

    # setup parameters
    for i in range(code.co_argcount):
        variables.append(context.param("int", code.co_varnames[i]))

    func = context.exported_function("int", name, variables)

    # allocate blocks
    blocks = []
    block_map = {}
    current_block_pos = None
    for instruction in dis.get_instructions(code):
        if current_block_pos is None:
            current_block_pos = instruction.offset
        if instruction.opname in block_boundaries:
            block = context.block(func)
            blocks.append(block)
            block_map[current_block_pos] = block
            current_block_pos = None

    print(block_map)

    # setup locals
    for i in range(code.co_argcount, code.co_nlocals):
        variables.append(context.local(func, "int", code.co_varnames[i]))

    block_iter = iter(blocks)
    block = next(block_iter)

    for instruction in dis.get_instructions(code):
        opname = instruction.opname
        argval = instruction.argval
        arg = instruction.arg
        if opname == 'LOAD_CONST':
            # stack.append(argval)
            stack.append(context.integer(argval))
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
            block = next(block_iter, None)
            # ret = stack.pop()
        elif opname == 'POP_JUMP_IF_FALSE':
            next_block = next(block_iter)
            block.end_with_conditonal(stack.pop(), next_block, block_map[arg])
            block = next_block
        elif opname == 'JUMP_ABSOLUTE':
            block.end_with_jump(block_map[arg])
            block = next(block_iter)
        elif opname == 'SETUP_LOOP':
            next_block = next(block_iter)
            block.end_with_jump(next_block)
            block = next_block
        elif opname == 'POP_BLOCK':
            pass
        else:
            assert 0, "Unknown opname " + opname

        print('stack {}, variables {}, ret {}'.format(stack, variables, ret))
