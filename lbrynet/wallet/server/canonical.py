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
        return '#'+self.short_id


def register_canonical_functions(connection):
    connection.create_aggregate("shortest_id", 2, FindShortestID)
