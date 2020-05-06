import time
import json
from hashlib import sha256
from collections import UserDict


class TimestampedPreferences(UserDict):

    def __init__(self, d: dict = None):
        super().__init__()
        if d is not None:
            self.data = d.copy()

    def __getitem__(self, key):
        return self.data[key]['value']

    def __setitem__(self, key, value):
        self.data[key] = {
            'value': value,
            'ts': time.time()
        }

    def __repr__(self):
        return repr(self.to_dict_without_ts())

    def to_dict_without_ts(self):
        return {
            key: value['value'] for key, value in self.data.items()
        }

    @property
    def hash(self):
        return sha256(json.dumps(self.data).encode()).digest()

    def merge(self, other: dict):
        for key, value in other.items():
            if key in self.data and value['ts'] < self.data[key]['ts']:
                continue
            self.data[key] = value
