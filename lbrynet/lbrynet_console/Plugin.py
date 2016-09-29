from yapsy.IPlugin import IPlugin


class Plugin(IPlugin):

    def __init__(self):
        IPlugin.__init__(self)

    def setup(self, lbry_console):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError