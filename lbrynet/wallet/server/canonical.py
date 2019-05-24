from binascii import hexlify


class FindShortestID:
    __slots__ = 'short_id', 'new_id'

    def __init__(self):
        self.short_id = b''
        self.new_id = None

    def step(self, other_hash, new_hash):
        if self.new_id is None:
            self.new_id = hexlify(new_hash[::-1])
        other_id = hexlify(other_hash[::-1])
        for i in range(len(self.new_id)):
            if other_id[i] != self.new_id[i]:
                if i > len(self.short_id)-1:
                    self.short_id = self.new_id[:i+1]
                break

    def finalize(self):
        if self.short_id:
            return '#'+self.short_id.decode()
        return ''


def register_canonical_functions(connection):
    connection.create_aggregate("shortest_id", 2, FindShortestID)
