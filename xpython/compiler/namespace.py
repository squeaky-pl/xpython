from collections import OrderedDict

from xpython import CompilerResult
from xpython.compiler import AbstractCompiler
from xpython.compiler.function import FunctionCompiler
from xpython.nodes import Function, ConstKeyMap, Name, Global, Class
from xpython.typing import struct


class NamespaceCompiler(AbstractCompiler):
    def __init__(self, context, ffi, types, code):
        self.types = types

        super().__init__(context, ffi, code)
        self.names = OrderedDict([
            ('struct', struct), ('void', 'void')])

    def log(self):
        print(self.stack)

    def make_function(self, instruction):
        ANNOTATION_DICTIONARY = 0x04
        flags = instruction.arg

        annotations = None
        if flags & ANNOTATION_DICTIONARY:
            flags ^= ANNOTATION_DICTIONARY
            annotations = True

        assert flags == 0

        qualname = self.stack.pop().value
        code = self.stack.pop()

        if annotations:
            annotations = self.stack.pop().value

        self.stack.append(Function(qualname, code, annotations))

    def store_name(self, instruction):
        arg = self.stack.pop()
        self.names[instruction.argval] = arg

    def load_name(self, instruction):
        self.stack.append(self.names[instruction.argval])

    def load_build_class(self, instruction):
        self.stack.append(Global('build_class'))

    def build_const_key_map(self, instruction):
        keys = self.stack.pop().value
        arguments = []
        for _ in range(instruction.arg):
            arguments.insert(0, self.stack.pop())

        map = ConstKeyMap(OrderedDict(zip(keys, arguments)))
        self.stack.append(map)

    def call_function(self, instruction):
        arguments = []
        for _ in range(instruction.arg):
            arguments.insert(0, self.stack.pop())
        f = self.stack.pop()

        if getattr(f, 'name', None) and f.name == 'build_class':
            self.stack.append(Class(arguments[1], arguments[0]))

            return

        if f is struct:
            arguments = [a.value for a in arguments]
            self.stack.append(struct(*arguments))

            return

        assert 0

    def return_value(self, instruction):
        self.stack.pop()

    def compile(self):
        self.emit()

        for name, item in self.names.items():
            if not isinstance(item, Function):
                continue

            ann = item.annotations
            compiler = FunctionCompiler(
                self.context, self.ffi, self.types, item.code,
                ann['return'], name,
                [v for k, v in ann.items() if k != 'return'])
            compiler.setup_function()
            compiler.setup_blocks()
            compiler.emit()

        return CompilerResult(self, self.context.compile())
