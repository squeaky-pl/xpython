def byte(x):
    assert 0 <= x <= 0xff


def unsigned(x):
    assert 0 <= x <= 0xffff_ffff_ffff_ffff


class struct:
    def __init__(self, name, *fields):
        self.name = name
        self.fields = fields
