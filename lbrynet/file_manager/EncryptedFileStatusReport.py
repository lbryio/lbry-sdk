class EncryptedFileStatusReport(object):
    def __init__(self, name, num_completed, num_known, running_status):
        self.name = name
        self.num_completed = num_completed
        self.num_known = num_known
        self.running_status = running_status
