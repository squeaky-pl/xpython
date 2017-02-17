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


class ByRef:
    needs_temporary = False


class RawMem(Type, ByRef):
    def build(self):
        char = self.context.type('char')
        self.ctype = self.context.pointer_type(char)

    @property
    def cname(self):
        return 'char*'


class Field:
    def __init__(self, name, typ, cfield):
        self.name = name
        self.typ = typ
        self.cfield = cfield


class Struct(Type):
    needs_temporary = False

    def build(self):
        self.fields = OrderedDict(
            (name, Field(name, typ, self.context.field(typ.ctype, name)))
            for typ, name in self.fields)

        self._ctype = self.context.struct_type(
            self.name, list(f.cfield for f in self.fields.values()))
        self.ctype = self.context.pointer_type(self._ctype)

        cffi_template = "typedef struct {\n"
        for name, field in self.fields.items():
            cffi_template += "    {} {};\n".format(field.typ.cname, name)
        cffi_template += '} ' + self.name + ';'

        self.ffi.cdef(cffi_template)

    def store_attr(self, compiler, instruction):
        where = compiler.stack.pop()
        what = compiler.stack.pop()
        cfield = self.fields[instruction.argval].cfield
        context = compiler.context

        deref = compiler.context.dereference_field(
            where.tojit(context), cfield)

        compiler.block.add_assignment(deref, what.tojit(context))

    def load_attribute(self, compiler, where, name):
        cfield = self.fields[name].cfield
        context = compiler.context

        deref = context.dereference_field(
            where.tojit(context), cfield)

        rvalue = Rvalue(self.fields[name].typ, '.' + name, deref)

        if self.fields[name].typ.needs_temporary:
            tmp = compiler.temporary(rvalue)

            compiler.block.add_assignment(
                tmp.tojit(context),
                rvalue.tojit(context))

            return tmp

        return rvalue

    def load_attr(self, compiler, instruction):
        where = compiler.stack.pop()
        name = instruction.argval

        compiler.stack.append(self.load_attribute(compiler, where, name))

    @property
    def cname(self):
        return self.name + '*'

    def __str__(self):
        return self.name


class Buffer(Struct):
    name = 'buffer'
    fields = [(Default, 'size'), (RawMem, 'data')]

    def build(self):
        super().build()

        abort = self.context.imported_function("void", "abort")

        # bound check code
        buffer_param = self.context.param(self.ctype, 'buffer')
        index_param = self.context.param(
            self.fields['size'].typ.ctype, 'index')
        self.bound_check = self.context.internal_function(
             "void", "bound_check", [buffer_param, index_param])

        cmp_block = self.context.block(self.bound_check)
        abort_block = self.context.block(self.bound_check)
        ret_block = self.context.block(self.bound_check)

        size = self.context.dereference_field(
            buffer_param, self.fields['size'].cfield)
        comparison = self.context.comparison('<', index_param, size)
        cmp_block.end_with_conditonal(comparison, ret_block, abort_block)

        abort_call = self.context.call(abort)
        abort_block.add_eval(abort_call)
        abort_block.end_with_void_return()

        ret_block.end_with_void_return()

    def len_call(self, compiler, argument):
        return self.load_attribute(compiler, argument, 'size')

    def binary_subscr(self, compiler, instruction):
        index = compiler.stack.pop()
        where = compiler.stack.pop()
        context = compiler.context

        assert isinstance(index.typ, Default), "index must be integer"
        assert isinstance(where.typ, Buffer), "where must be buffer"

        if True:
            bound_check_call = context.call(
                self.bound_check,
                [where.tojit(context), index.tojit(context)])
            compiler.block.add_eval(bound_check_call)

        data = self.load_attribute(compiler, where, 'data')

        rvalue = Rvalue(
            compiler.types.byte, "[]",
            context.array_access(data.tojit(context), index.tojit(context)))

        tmp = compiler.temporary(rvalue)

        compiler.block.add_assignment(
            tmp.tojit(context),
            rvalue.tojit(context))

        compiler.stack.append(tmp)

    def store_subscr(self, compiler, instruction):
        index = compiler.stack.pop()
        where = compiler.stack.pop()
        what = compiler.stack.pop()
        context = compiler.context

        assert isinstance(index.typ, Default), "index must be integer"
        assert isinstance(where.typ, Buffer), "where must be buffer"
        assert isinstance(what.typ, Byte), "what must be byte"

        data = self.load_attribute(compiler, where, 'data')

        if True:
            bound_check_call = context.call(
                self.bound_check,
                [where.tojit(context), index.tojit(context)])
            compiler.block.add_eval(bound_check_call)

        lvalue = context.array_access(
            data.tojit(self.context), index.tojit(self.context))

        compiler.block.add_assignment(lvalue, what.tojit(self.context))


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
            fields = [(self.get_type(t), n) for n, t in typid.fields.items()]
            typ = type(
                typid.name, (Struct,), {"name": typid.name, "fields": fields})

            return self._get_type(typ)
        elif type(typid) is type and issubclass(typid, Type):
            return self._get_type(typid)

        return self._get_type(str_to_typ[typid])

    def _get_type(self, typ):
        if typ in self.cache:
            return self.cache[typ]

        instance = typ(self.context, self.ffi)

        if issubclass(typ, Struct):
            instance.fields = [
                (self._get_type(t), n) for t, n in typ.fields]

        instance.build()
        self.cache[typ] = instance

        return self.cache[typ]
