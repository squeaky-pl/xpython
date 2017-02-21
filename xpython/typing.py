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

    def __repr__(self):
        r = '<struct {} '.format(self.name)
        r += ','.join(n + ': ' + str(t) for n, t in self.fields.items())
        r += '>'

        return r


PyObject = struct(
    'PyObject',

    ('ob_refcnt', 'ssize'),
    ('ob_type', 'opaque'))


class py_struct(struct):
    def __init__(self, name, *fields):
        pass


class struct_instance:
    def __init__(self, typ, values):
        self.__type = typ
        for k, v in values.items():
            setattr(self, k, v)

    def __repr__(self):
        r = '<' + self.__type.name + ' '
        r += ' '.join(
            f + '=' + str(getattr(self, f)) for f in self.__type.fields)
        r += '>'

        return r
