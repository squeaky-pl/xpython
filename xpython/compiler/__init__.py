import dis

from xpython.nodes import Constant, Location


class AbstractCompiler:
    def __init__(self, context, ffi, code):
        self.context = context
        self.ffi = ffi
        self.code = code
        self.stack = []

    def emit(self):
        for instruction in dis.get_instructions(self.code):
            if instruction.starts_line:
                self.location = Location(
                    self.code.co_filename, instruction.starts_line)

            self.log()

            try:
                handler = getattr(self, instruction.opname.lower())
            except AttributeError:
                assert 0, "Unknown opname " + instruction.opname

            handler(instruction)

    def load_const(self, instruction):
        self.stack.append(Constant.frompy(self, instruction.argval))
