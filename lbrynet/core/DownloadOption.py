class DownloadOptionChoice(object):
    """A possible choice that can be picked for some option.

    An option can have one or more choices that can be picked from.
    """
    def __init__(self, value, short_description, long_description, bool_options_description=None):
        self.value = value
        self.short_description = short_description
        self.long_description = long_description
        self.bool_options_description = bool_options_description


class DownloadOption(object):
    """An option for a user to select a value from several different choices."""
    def __init__(self, option_types, long_description, short_description, default_value,
                 default_value_description):
        self.option_types = option_types
        self.long_description = long_description
        self.short_description = short_description
        self.default_value = default_value
        self.default_value_description = default_value_description