from xpython.typing import struct, struct_value
from xpython.nodes import Rvalue, GlobalVar, Constant
from collections import OrderedDict


DEFAULT_INTEGER_CTYPE = 'int'
OVERFLOW_CHECKS = True
BOUND_CHECKS = True


class Type:
    def __init__(self, context, ffi):
        self.context = context
        self.ffi = ffi

    def __str__(self):
        return type(self).__name__

    def default_jit_constant(self, context):
        return self.jit_constnat(context, self.default)

    def default_constant(self):
        return Constant(self, self.default)


class Void(Type):
    cname = 'void'

    def build(self):
        self.ctype = self.context.type("void")


class Ptr(Type):
    default = None

    def jit_constant(self, context, value):
        assert value is None

        return context.null(self.ctype)


class Opaque(Ptr):
    cname = 'void*'

    def build(self):
        self.ctype = self.context.type("void*")


class ByCopy:
    needs_temporary = True


# abstract
class Integer(Type, ByCopy):
    default = 0

    def build(self):
        self.ctype = self.context.type(self.cname)

    def binary(self, compiler, op):
        b = compiler.stack.pop()
        a = compiler.stack.pop()
        context = compiler.context

        if OVERFLOW_CHECKS and op in self.safe_arithmetic:
            func = self.safe_arithmetic[op]
            result = context.call(
                func, [a.tojit(context), b.tojit(context)])
        else:
            result = context.binary(
                op, self.ctype, a.tojit(context), b.tojit(context))

        compiler.stack.append(Rvalue(self, op, result))

    def binary_add(self, compiler):
        self.binary(compiler, '+')

    inplace_add = binary_add

    def binary_subtract(self, compiler):
        self.binary(compiler, '-')

    inplace_subtract = binary_subtract

    def binary_multiply(self, compiler):
        self.binary(compiler, '*')

    inplace_multiply = binary_multiply

    def binary_floor_divide(self, compiler):
        # FIXME: this only works for positive numbers!
        # http://stackoverflow.com/questions/828092/python-style-integer-division-modulus-in-c
        self.binary(compiler, '/')

    inplace_floor_divide = binary_floor_divide

    def jit_constant(self, context, value):
        return context.integer(
            value, self.ctype)


class Default(Integer):
    cname = DEFAULT_INTEGER_CTYPE

    def build(self):
        super().build()

        # arithmetic check code
        self.safe_arithmetic = {}
        false = self.context.false()
        abort = self.context.imported_function("void", "abort")
        for op, name in {'+': 'add', '-': 'sub', '*': 'mul'}.items():
            a = self.context.param(self.ctype, 'a')
            b = self.context.param(self.ctype, 'b')
            builtin = self.context.builtin_function(
                '__builtin_{}_overflow'.format(name))

            f = self.context.internal_function(
                self.ctype, "safe_{}".format(name), [a, b])
            result = self.context.local(
                f, self.ctype, 'result')
            result_p = self.context.address(result)
            overflow = self.context.local(
                f, 'bool', 'overflow')

            cmp_block = self.context.block(f)
            abort_block = self.context.block(f)
            ret_block = self.context.block(f)

            builtin_call = self.context.call(builtin, [a, b, result_p])
            cmp_block.add_assignment(overflow, builtin_call)
            comparison = self.context.comparison('==', overflow, false)
            cmp_block.end_with_conditonal(comparison, ret_block, abort_block)

            abort_call = self.context.call(abort)
            abort_block.add_eval(abort_call)
            abort_block.end_with_jump(ret_block)

            ret_block.end_with_return(result)

            self.safe_arithmetic[op] = f


class SSize(Integer):
    cname = 'ssize_t'


class Byte(Integer):
    cname = 'char'


class UInt(Integer):
    cname = 'unsigned int'


class Unsigned(Integer):
    cname = 'unsigned long'


class ByRef:
    needs_temporary = False


class RawMem(Ptr, ByRef):
    def build(self):
        char = self.context.type('char')
        self.ctype = self.context.pointer_type(char)

    @property
    def cname(self):
        return 'char*'


class CStr(Ptr, ByRef):
    cname = 'const char*'

    def build(self):
        self.ctype = self.context.type('const char*')

    def jit_constant(self, context, value):
        if value is None:
            return Ptr.jit_constant(self, context, value)

        return context.string_literal(value)


class Field:
    def __init__(self, name, typ, cfield):
        self.name = name
        self.typ = typ
        self.cfield = cfield


class AbstractStruct(Type):
    def store_attribute(self, compiler, where, name, what):
        context = compiler.context

        cfield = self.fields[name].cfield

        accessed = self.access_field_lvalue(where.tojit(context), cfield)

        compiler.block.add_assignment(accessed, what.tojit(context))

    def store_attr(self, compiler, instruction):
        where = compiler.stack.pop()
        what = compiler.stack.pop()
        name = instruction.argval

        self.store_attribute(compiler, where, name, what)

    def load_attribute(self, compiler, where, name):
        context = compiler.context

        field = self.fields[name]
        cfield = field.cfield
        typ = field.typ

        accessed = self.access_field_lvalue(where.tojit(context), cfield)

        rvalue = Rvalue(typ, '.' + name, accessed)

        if typ.needs_temporary:
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


class ValueStruct(AbstractStruct):
    needs_temporary = False

    def store_name(self, compiler, instruction):
        name = instruction.argval
        context = compiler.context
        location = compiler.location.tojit(context)
        lvalue = context.exported_global(
            self.ctype, name, location)

        return GlobalVar(self, name, lvalue)


class Struct(Ptr, AbstractStruct):
    needs_temporary = False

    def build(self):
        self.fields = OrderedDict(
            (name, Field(name, typ, self.context.field(typ.ctype, name)))
            for typ, name in self.fields)

        value_ctype = self.context.struct_type(
            self.name, list(f.cfield for f in self.fields.values()))
        self.ctype = self.context.pointer_type(value_ctype)
        self.access_field = self.context.dereference_field
        self.access_field_lvalue = self.access_field

        self.value = ValueStruct(self.context, self.ffi)
        self.value.fields = self.fields
        self.value.ctype = value_ctype
        self.value.cname = self.name
        self.value.access_field = self.context.access_field
        self.value.access_field_lvalue = self.context.access_field_lvalue

        cffi_template = "typedef struct {\n"
        for name, field in self.fields.items():
            cffi_template += "    {} {};\n".format(field.typ.cname, name)
        cffi_template += '} ' + self.name + ';'

        self.ffi.cdef(cffi_template)

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

        if BOUND_CHECKS:
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

        if BOUND_CHECKS:
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
        self.name_cache = {}

    @property
    def opaque(self):
        return self._get_type(Opaque)

    @property
    def buffer(self):
        return self._get_type(Buffer)

    @property
    def unsigned(self):
        return self._get_type(Unsigned)

    @property
    def default(self):
        return self._get_type(Default)

    @property
    def byte(self):
        return self._get_type(Byte)

    @property
    def uint(self):
        return self._get_type(UInt)

    @property
    def ssize(self):
        return self._get_type(SSize)

    @property
    def cstr(self):
        return self._get_type(CStr)

    def get_type(self, typid):
        str_to_typ = {
            'void': Void,
            'opaque': Opaque,
            ...: Opaque,
            'int': Default,
            int: Default,
            'uint': UInt,
            'unsigned': Unsigned,
            'ssize': SSize,
            'default': Default,
            'byte': Byte,
            'buffer': Buffer,
            'cstr': CStr
        }

        if isinstance(typid, struct):
            fields = [(self.get_type(t), n) for n, t in typid.fields.items()]
            typ = type(
                typid.name, (Struct,), {"name": typid.name, "fields": fields})

            return self._get_type(typ)
        elif isinstance(typid, struct_value):
            return self.get_type(typid.instance).value
        elif type(typid) is type and issubclass(typid, Type):
            return self._get_type(typid)

        return self._get_type(str_to_typ[typid])

    def _get_type(self, typ):
        if isinstance(typ, Type):
            return typ

        if typ in self.cache:
            return self.cache[typ]

        if issubclass(typ, Struct) and typ.__name__ in self.name_cache:
            return self.name_cache[typ.__name__]

        instance = typ(self.context, self.ffi)

        if issubclass(typ, Struct):
            instance.fields = [
                (self._get_type(t), n) for t, n in typ.fields]

        instance.build()

        if issubclass(typ, Struct):
            self.name_cache[typ.__name__] = instance
        else:
            self.cache[typ] = instance

        return instance
