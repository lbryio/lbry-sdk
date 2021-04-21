class FindShortestID:
    __slots__ = 'short_id', 'new_id'

    def __init__(self):
        self.short_id = ''
        self.new_id = None

    def step(self, other_id, new_id):
        self.new_id = new_id
        for i in range(len(self.new_id)):
            if other_id[i] != self.new_id[i]:
                if i > len(self.short_id)-1:
                    self.short_id = self.new_id[:i+1]
                break

    def finalize(self):
        if self.short_id:
            return ':'+self.short_id

    @classmethod
    def factory(cls):
        return cls(), cls.step, cls.finalize


def register_canonical_functions(connection):
    connection.createaggregatefunction("shortest_id", FindShortestID.factory, 2)
