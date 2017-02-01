import logging


class Handler(logging.Handler):
    """A logging handler that reports errors to the analytics manager"""
    def __init__(self, manager, level=logging.ERROR):
        self.manager = manager
        logging.Handler.__init__(self, level)

    def emit(self, record):
        self.manager.send_error(record)
