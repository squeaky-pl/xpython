class CFunction:
    def __init__(self, context, ret_type, name, param_types):
        self.context = context
        self.cfunction = context.imported_function(
            ret_type, name, param_types)

    def __call__(self, *params):
        return self.context.call(self.cfunction, params)


class CFunctions:
    def __init__(self, context):
        self.context = context
        self.cache = {}

    @property
    def printf(self):
        return self.get_function('int', 'printf', ['const char*', ...])

    def get_function(self, ret_type, name, param_types):
        if name in self.cache:
            return self.cache[name]

        function = CFunction(self.context, ret_type, name, param_types)
        self.cache[name] = function

        return function
