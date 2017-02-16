xtype_to_c = {
    int: "int",
    "byte": "char",
    "unsigned": "unsigned long",
    "signed": "signed long",
    "void": "void",

    "buffer": "buffer*"
}


DEFAULT_INTEGER_TYPE = int
DEFAULT_INTEGER_CTYPE = xtype_to_c[DEFAULT_INTEGER_TYPE]


class Type:
    def __init__(self, context, ffi):
        self.context = context
        self.ffi = ffi


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
        return self.get_type(
            'buffer', Buffer(self.context, self.ffi))

    def get_type(self, name, typ):
        if name in self.cache:
            return self.cache[name]

        typ.build()
        self.cache[name] = typ

        return self.cache[name]
