from xpython.typing import struct


PyObject = struct(
    'PyObject',

    ('ob_refcnt', 'ssize'),
    ('ob_type', ...))


PyVarObject = struct(
    'PyVarObject',

    ('ob_base', PyObject.value),
    ('ob_size', 'ssize')
)


PyObjectType = struct(
    'PyObjectType',

    ('ob_base', PyVarObject.value),
    ('tp_name', 'cstr'),
    ('tp_basicsize', 'ssize'),
    ('tp_itemsize', 'ssize'),

    ('tp_dealloc', ...),
    ('tp_print', ...),
    ('tp_getattr', ...),
    ('tp_setattr', ...),
    ('tp_as_async', ...),
    ('tp_repr', ...),

    ('tp_as_number', ...),
    ('tp_as_sequence', ...),
    ('tp_as_mapping', ...),

    ('tp_hash', ...),
    ('tp_call', ...),
    ('tp_str', ...),
    ('tp_getattro', ...),
    ('tp_setattro', ...),

    ('tp_as_buffer', ...),
    ('tp_flags', 'unsigned'),

    ('tp_doc', 'cstr'),

    ('tp_traverse', ...),

    ('tp_clear', ...),

    ('tp_richcompare', ...),

    ('tp_weaklistoffset', 'ssize'),

    ('tp_iter', ...),
    ('tp_iternext', ...),

    ('tp_methods', ...),
    ('tp_members', ...),
    ('tp_getset', ...),
    ('tp_base', ...),
    ('tp_dict', ...),
    ('tp_descr_get', ...),
    ('tp_descr_set', ...),
    ('tp_dictoffset', 'ssize'),
    ('tp_init', ...),
    ('tp_alloc', ...),
    ('tp_new', ...),
    ('tp_free', ...),
    ('tp_is_gc', ...),
    ('tp_bases', ...),
    ('tp_mro', ...),
    ('tp_cache', ...),
    ('tp_subclass', ...),
    ('tp_weaklist', ...),
    ('tp_del', ...),

    ('tp_version_tag', 'uint'),

    ('tp_finalize', ...)
)


class py_struct(struct):
    def __init__(self, name, *fields):
        super().__init__(name, ('ob_base', PyObject.value), *fields)


def export_class(klass):
    pass
