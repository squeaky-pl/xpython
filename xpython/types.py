DEFAULT_INTEGER_CTYPE = 'int'


class Type:
    def __init__(self, context, ffi):
        self.context = context
        self.ffi = ffi

    def __str__(self):
        return type(self).__name__


class Void(Type):
    def build(self):
        self.ctype = self.context.type("void")


class Default(Type):
    def build(self):
        self.ctype = self.context.type(DEFAULT_INTEGER_CTYPE)


class Byte(Type):
    def build(self):
        self.ctype = self.context.type('char')


class Buffer(Type):
    def build(self):
        char_p = self.context.pointer_type("char")
        self.size_field = self.context.field(DEFAULT_INTEGER_CTYPE, "size")
        self.data_field = self.context.field(char_p, "data")
        self.buffer_type = self.context.struct_type(
            "buffer", [self.size_field, self.data_field])
        self.ctype = self.context.pointer_type(self.buffer_type)

        self.ffi.cdef("""
            typedef struct {{
                {size_type} size;
                char* data;
            }} buffer;
        """.format(size_type=DEFAULT_INTEGER_CTYPE))


class Types:
    def __init__(self, context, ffi):
        self.context = context
        self.ffi = ffi
        self.cache = {}

    @property
    def buffer(self):
        return self._get_type(Buffer)

    def get_type(self, name):
        str_to_typ = {
            'void': Void,
            int: Default,
            'default': Default,
            'byte': Byte,
            'buffer': Buffer
        }

        return self._get_type(str_to_typ[name])

    def _get_type(self, typ):
        if typ in self.cache:
            return self.cache[typ]

        instance = typ(self.context, self.ffi)
        instance.build()
        self.cache[typ] = instance

        return self.cache[typ]
