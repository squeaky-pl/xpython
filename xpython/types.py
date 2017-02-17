from xpython.typing import struct
from xpython.nodes import Rvalue
from collections import OrderedDict


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

    @property
    def cname(self):
        return 'void'


class ByCopy:
    needs_temporary = True


class Default(Type, ByCopy):
    def build(self):
        self.ctype = self.context.type(DEFAULT_INTEGER_CTYPE)

    @property
    def cname(self):
        return DEFAULT_INTEGER_CTYPE


class Byte(Type, ByCopy):
    def build(self):
        self.ctype = self.context.type('char')

    @property
    def cname(self):
        return 'char'


class Struct(Type):
    needs_temporary = False

    def build(self):
        self.fields = OrderedDict(
            (name, typ) for typ, name in self.fields)
        self.cfields = OrderedDict(
            (name, self.context.field(typ.ctype, name))
            for name, typ in self.fields.items())

        self._ctype = self.context.struct_type(
            self.name, list(self.cfields.values()))
        self.ctype = self.context.pointer_type(self._ctype)

        cffi_template = "typedef struct {\n"
        for name, typ in self.fields.items():
            cffi_template += "    {} {};\n".format(typ.cname, name)
        cffi_template += '} ' + self.name + ';'

        self.ffi.cdef(cffi_template)

    def store_attr(self, compiler, instruction):
        where = compiler.stack.pop()
        what = compiler.stack.pop()
        cfield = self.cfields[instruction.argval]
        context = compiler.context

        deref = compiler.context.dereference_field(
            where.tojit(context), cfield)

        compiler.block.add_assignment(deref, what.tojit(context))

    def load_attr(self, compiler, instruction):
        where = compiler.stack.pop()
        name = instruction.argval
        cfield = self.cfields[name]
        context = compiler.context

        deref = compiler.context.dereference_field(
            where.tojit(context), cfield)

        compiler.stack.append(Rvalue(
            self.fields[name], '.' + name, deref))

    @property
    def cname(self):
        return self.name + '*'

    def __str__(self):
        return self.name


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

    @property
    def cname(self):
        return 'buffer*'


class Types:
    def __init__(self, context, ffi):
        self.context = context
        self.ffi = ffi
        self.cache = {}

    @property
    def buffer(self):
        return self._get_type(Buffer)

    @property
    def default(self):
        return self._get_type(Default)

    @property
    def byte(self):
        return self._get_type(Byte)

    def get_type(self, typid):
        str_to_typ = {
            'void': Void,
            int: Default,
            'default': Default,
            'byte': Byte,
            'buffer': Buffer
        }

        if isinstance(typid, struct):
            fields = [(self.get_type(t), name) for t, name in typid.fields]
            typ = type(
                typid.name, (Struct,), {"name": typid.name, "fields": fields})

            return self._get_type(typ)

        return self._get_type(str_to_typ[typid])

    def _get_type(self, typ):
        if typ in self.cache:
            return self.cache[typ]

        instance = typ(self.context, self.ffi)
        instance.build()
        self.cache[typ] = instance

        return self.cache[typ]
