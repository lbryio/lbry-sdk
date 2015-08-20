class DownloadOption(object):
    def __init__(self, option_types, long_description, short_description, default):
        self.option_types = option_types
        self.long_description = long_description
        self.short_description = short_description
        self.default = default