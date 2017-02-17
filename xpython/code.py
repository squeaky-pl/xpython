import tempfile


class Code:
    def __init__(self, code):
        self.code = code

    def first_function(self):
        return self.code.co_consts[0]


def from_string(value, tmp=True):
    path = '<unknown>'
    if tmp:
        _, path = tempfile.mkstemp('.py', 'xpython_')
        with open(path, "w") as f:
            f.write(value)

    compiled = compile(value, path, 'exec')

    return Code(compiled)
