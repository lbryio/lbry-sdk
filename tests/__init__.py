# log_support setups the default Logger class
# and so we need to ensure that it is also
# setup for the tests
from lbrynet.core import log_support
from lbrynet import conf


# TODO: stop doing this, would be better to mock out the settings
conf.initialize_settings()
