from xpython.compiler.namespace import NamespaceCompiler
from xpython.compiler.cls import ClassCompiler
from xpython.nodes import Class
from xpython.types import Types


class ModuleCompiler(NamespaceCompiler):
    def __init__(self, context, ffi, code):
        self.types = Types(context, ffi)

        super().__init__(context, ffi, self.types, code)

        self.class_compilers = {}

    def emit(self):
        super().emit()

        for name, value in self.names.items():
            if not isinstance(value, Class):
                continue

            compiler = ClassCompiler(
                self.context, self.ffi, self.types, value.function.code)
            self.class_compilers[name] = compiler
            compiler.emit()
