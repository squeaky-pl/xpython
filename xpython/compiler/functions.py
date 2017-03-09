from xpython.types import ValueStruct
from xpython.nodes import Rvalue


def default(compiler, arguments):
    assert len(arguments) == 1
    argument = arguments[0]

    for field in argument.typ.fields.values():
        if isinstance(field.typ, ValueStruct):
            default(
                compiler,
                [argument.typ.load_attribute(compiler, argument, field.name)])
        else:
            argument.typ.store_attribute(
                compiler, argument, field.name, field.typ.default_constant())


def PyModule_Create(compiler, arguments):
    assert len(arguments) == 1
    argument = arguments[0]

    context = compiler.context

    PyModule_Create2 = context.imported_function(
        "void*", "PyModule_Create2", ["void*", "int"])
    PyModule_Create2_call = context.call(
        PyModule_Create2,
        [context.address(argument.tojit(context)), context.integer(3)])

    return Rvalue(
        compiler.types.opaque, "PyModule_Create2()", PyModule_Create2_call)


def PyType_Ready(compiler, arguments):
    assert len(arguments) == 1
    argument = arguments[0]

    context = compiler.context

    PyType_Ready = context.imported_function(
        "int", "PyType_Ready", ["void*"])
    PyType_Ready_call = context.call(
        PyType_Ready, [context.address(argument.tojit(context))])

    return Rvalue(
        compiler.types.int, "PyType_Ready()", PyType_Ready_call)
