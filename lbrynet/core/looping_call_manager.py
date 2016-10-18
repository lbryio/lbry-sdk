class LoopingCallManager(object):
    def __init__(self, calls=None):
        self.calls = calls or {}

    def register_looping_call(self, name, call):
        assert name not in self.calls, '{} is already registered'.format(name)
        self.calls[name] = call

    def start(self, name, *args):
        lcall = self.calls[name]
        if not lcall.running:
            lcall.start(*args)

    def stop(self, name):
        self.calls[name].stop()

    def shutdown(self):
        for lcall in self.calls.itervalues():
            if lcall.running:
                lcall.stop()
