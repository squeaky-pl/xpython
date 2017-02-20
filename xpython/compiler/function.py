from collections import OrderedDict
import dis

from xpython import CompilerResult
from xpython.compiler import AbstractCompiler
from xpython.c import CFunctions
from xpython.types import Void
from xpython.nodes import Rvalue, Constant, Global, Unreachable, Local, \
    Temporary, Param


block_boundaries = [
    'RETURN_VALUE', 'POP_JUMP_IF_FALSE', 'POP_JUMP_IF_TRUE', 'SETUP_LOOP',
    'JUMP_ABSOLUTE', 'BREAK_LOOP'
]


class FunctionCompiler(AbstractCompiler):
    def __init__(self, context, ffi, types, code, ret_type, name, param_types):
        self.context = context
        self.code = code
        self.name = name
        self.stack = []
        self.temporaries = 0

        self.ffi = ffi
        self.types = types

        self.ret_type = self.types.get_type(ret_type)
        self.param_types = [self.types.get_type(p) for p in param_types]

        self.c = CFunctions(context)

    def get_print(self, params):
        formats = {'int': b'%d'}

        param_types = [p.typ for p in params]
#        name = 'print_' + '_'.join(p.__name__ for p in param_types)
        cparam_types = [t.ctype for t in param_types]
        formatstr = self.context.string_literal(
            b' '.join(formats[t] for t in cparam_types) + b'\n')

        return self.c.printf(
            formatstr, *[p.tojit(self.context) for p in params])

    def setup_function(self):
        code = self.code
        self.variables = []
        params = []

        # setup parameters
        for i in range(code.co_argcount):
            self.variables.append(
                Param(self.param_types[i], code.co_varnames[i]))
            params = [v.tojit(self.context) for v in self.variables]

        location = self.context.location(
            self.code.co_filename, self.code.co_firstlineno, 0)

        self.function = self.context.exported_function(
            self.ret_type.ctype, self.name, params, location)

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

    def log(self):
        print('block {}, stack {}'.format(self.block, self.stack))

    def load_global(self, instruction):
        self.stack.append(Global(instruction.argval))

    def store_fast(self, instruction):
        variable = self.variables[instruction.arg]
        a = self.stack.pop()
        if not variable.typ:
            variable.typ = a.typ

        self.block.add_assignment(
            variable.tojit(self.context),
            a.tojit(self.context), self.location.tojit(self.context))

    def temporary(self, src):
        tmp = Temporary(self.function, src.typ, self.temporaries, src)
        self.temporaries += 1
        return tmp

    def load_fast(self, instruction):
        var = self.variables[instruction.arg]

        if var.typ.needs_temporary:
            tmp = self.temporary(var)

            self.block.add_assignment(
                tmp.tojit(self.context),
                var.tojit(self.context),
                self.location.tojit(self.context))

            push = tmp
        else:
            push = var

        self.stack.append(push)

    def binary_add(self, instruction):
        self.stack[-1].typ.binary_add(self)

    def inplace_add(self, instruction):
        self.stack[-1].typ.binary_add(self)

    def binary_subtract(self, instruction):
        self.stack[-1].typ.inplace_subtract(self)

    def inplace_subtract(self, instruction):
        self.stack[-1].typ.binary_subtract(self)

    def binary_multiply(self, instruction):
        self.stack[-1].typ.binary_multiply(self)

    def inplace_multiply(self, instruction):
        self.stack[-1].typ.inplace_multiply(self)

    def binary_floor_divide(self, instruction):
        self.stack[-1].typ.binary_floor_divide(self)

    def inplace_floor_divide(self, instruction):
        self.stack[-1].typ.inplace_floor_divide(self)

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
            self.stack.append(Constant.frompy(self, item))

    def rot_two(self, instruction):
        stack = self.stack
        stack[-1], stack[-2] = stack[-2], stack[-1]

    def rot_three(self, instruction):
        stack = self.stack
        stack[-1], stack[-2], stack[-3] = stack[-2], stack[-3], stack[-1]

    def dup_top(self, instruction):
        self.stack.append(self.stack[-1])

    def store_subscr(self, instruction):
        self.stack[-2].typ.store_subscr(self, instruction)

    def binary_subscr(self, instruction):
        self.stack[-2].typ.binary_subscr(self, instruction)

    def store_attr(self, instruction):
        self.stack[-1].typ.store_attr(self, instruction)

    def load_attr(self, instruction):
        self.stack[-1].typ.load_attr(self, instruction)

    def call_function(self, instruction):
        arguments = []
        for _ in range(instruction.arg):
            arguments.insert(0, self.stack.pop())
        function = self.stack.pop()

        if isinstance(function, Global):
            if function.name == 'abort' and instruction.arg == 0:
                __builtin_trap = self.context.builtin_function(
                    '__builtin_trap')
                trap_call = self.context.call(__builtin_trap)
                self.block.add_eval(trap_call)
                self.stack.append(Unreachable())

                return

            if function.name == 'byte' and instruction.arg == 1:
                rvalue = arguments[0]

                if isinstance(rvalue, Constant):
                    if 0 <= rvalue.value <= 0xff:
                        self.stack.append(
                            Constant(self.types.byte, rvalue.value))
                    else:
                        assert 0, "Constant out of bounds for byte"

                    return

            if function.name == 'print':
                call = self.get_print(arguments)

                self.block.add_eval(call)

                self.stack.append(None)

                return

            if instruction.arg == 1:
                f = getattr(arguments[0].typ, function.name + '_call')
                rvalue = f(self, arguments[0])
                self.stack.append(rvalue)

                return

        assert 0, "Don't know what to do with {}({})".format(
            function, arguments)

    def return_value(self, instruction):
        retval = self.stack.pop()
        if not isinstance(self.ret_type, Void):
            self.block.end_with_return(
                retval.tojit(self.context), self.location.tojit(self.context))
        else:
            self.block.end_with_void_return(self.location.tojit(self.context))

        self.block = next(self.block_iter, None)

    def pop_jump_if_false(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_conditonal(
            self.stack.pop().tojit(self.context),
            next_block, self.block_map[instruction.arg],
            self.location.tojit(self.context))
        self.block = next_block

    def pop_jump_if_true(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_conditonal(
            self.stack.pop().tojit(self.context),
            self.block_map[instruction.arg], next_block,
            self.location.tojit(self.context))
        self.block = next_block

    def pop_top(self, instruction):
        top = self.stack.pop()

        if isinstance(top, Unreachable):
            next_block = next(self.block_iter)
            self.block.end_with_jump(
                next_block, self.location.tojit(self.context))
            self.block = next_block

    def jump_absolute(self, instruction):
        self.block.end_with_jump(
            self.block_map[instruction.arg], self.location.tojit(self.context))
        self.block = next(self.block_iter)

    def break_loop(self, instruction):
        self.block.end_with_jump(
            self.block_stack[-1],
            self.location.tojit(self.context))
        self.block = next(self.block_iter)

    def setup_loop(self, instruction):
        self.block_stack.append(
            self.block_map[instruction.offset + instruction.arg])
        next_block = next(self.block_iter)
        self.block.end_with_jump(next_block, self.location.tojit(self.context))
        self.block = next_block

    def pop_block(self, instruction):
        next_block = next(self.block_iter)
        self.block.end_with_jump(next_block, self.location.tojit(self.context))
        self.block = next_block
        self.block_stack.pop()

    def compile(self):
        return CompilerResult(self, self.context.compile())
