from xpython.types import Buffer


class CffiBuffer:
    def __init__(self, ffi, data):
        self._data = ffi.new("char[]", data)
        self._cffi = ffi.new("buffer*")
        self._cffi.size = self.size
        self._cffi.data = self._data
        self.ffi = ffi

    @property
    def data(self):
        return self.ffi.unpack(self._data, self.size)

    @property
    def size(self):
        return len(self._data) - 1

    @property
    def cffi(self):
        return self._cffi


class CompilerResult:
    def __init__(self, compiler, result):
        self.compiler = compiler
        self.result = result

    def code(self, name):
        return self.result.code(name)

    def cffi(self, name):
        compiler = self.compiler
        code = self.result.code(name)

        cparams = ','.join(p.cname for p in compiler.param_types)
        cdef = compiler.ret_type.cname + "(*)(" + cparams + ")"

        return compiler.ffi.cast(cdef, code)

    def cffi_wrapper(self, name):
        def make_param(name, typ):
            if isinstance(typ, Buffer):
                return name + '.cffi'

            return name

        wrapper = "def wrapper_fun(cffi, ".format(name)
        compiler = self.compiler
        wrapper += ', '.join(
            'p{}'.format(i) for i, _ in enumerate(compiler.param_types))
        wrapper += '):\n'
        wrapper += '  return cffi('
        wrapper += ', '.join(
            make_param('p{}'.format(i), t)
            for i, t in enumerate(compiler.param_types))
        wrapper += ')'

        print(wrapper)

        exec(wrapper)

        import functools

        return functools.partial(locals()['wrapper_fun'], self.cffi(name))
