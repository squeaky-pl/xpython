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
        return '<Rvalue {}: {}>'.format(self.desc or '', self.typ)


class Constant(Rvalue):
    def __init__(self, typ, value):
        self.value = value
        super().__init__(typ)

    @classmethod
    def frompy(cls, compiler, value):
        if value is None:
            return None
        elif isinstance(value, tuple):
            return cls(tuple(type(i) for i in value), value)
        elif isinstance(value, int):
            return cls(compiler.types.default, value)

        assert 0

    def __repr__(self):
        return '<Constant {}: {}>'.format(self.value, self.typ)

    def _tojit(self, context):
        return context.integer(self.value, self.typ.ctype)


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
            self.desc, self.typ, id(self))

    def _tojit(self, context):
        return context.local(self.function, self.typ.ctype, self.desc)


class Temporary(Local):
    def __init__(self, function, typ, idx, src):
        self.src = src
        super().__init__(function, typ, '@' + str(idx))

    def __repr__(self):
        return '<Temporary {}: {} from {}>'.format(
            self.desc, self.typ, self.src.desc)


class Param(Rvalue):
    def __init__(self, typ, name):
        super().__init__(typ, name)

    def _tojit(self, context):
        return context.param(self.typ.ctype, self.desc)