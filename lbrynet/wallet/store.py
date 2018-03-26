import os
import json


class JSONStore(dict):

    def __init__(self, config, name):
        self.config = config
        self.path = os.path.join(self.config.path, name)
        self.load()

    def load(self):
        try:
            with open(self.path, 'r') as f:
                self.update(json.loads(f.read()))
        except:
            pass

    def save(self):
        with open(self.path, 'w') as f:
            s = json.dumps(self, indent=4, sort_keys=True)
            r = f.write(s)

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)
        self.save()

    def pop(self, key):
        if key in self.keys():
            dict.pop(self, key)
            self.save()
