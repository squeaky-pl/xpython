from xpython.types import ValueStruct


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
