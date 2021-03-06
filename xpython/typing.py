from collections import OrderedDict


def byte(x):
    assert 0 <= x <= 0xff


def unsigned(x):
    assert 0 <= x <= 0xffff_ffff_ffff_ffff


class struct:
    def __init__(self, name, *fields):
        self.name = name
        self.fields = OrderedDict(fields)

    def __call__(self, **kwargs):
        for name in kwargs:
            assert name in self.fields

        return struct_instance(self, kwargs)

    @property
    def value(self):
        return struct_value(self)

    def __repr__(self):
        r = '<struct {} '.format(self.name)
        r += ','.join(n + ': ' + str(t) for n, t in self.fields.items())
        r += '>'

        return r


class struct_value:
    def __init__(self, instance):
        self.instance = instance

    def __repr__(self):
        return '<struct_value {}>'.format(self.instance)


class struct_instance:
    def __init__(self, typ, values):
        self.__type = typ
        for k, v in values.items():
            setattr(self, k, v)

    @property
    def typ(self):
        return self.__type

    def __repr__(self):
        r = '<' + self.__type.name + ' '
        r += ' '.join(
            f + '=' + str(getattr(self, f, '<notini>')) for f in self.__type.fields)
        r += '>'

        return r
