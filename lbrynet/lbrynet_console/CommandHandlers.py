import logging
from zope.interface import implements
from twisted.internet import defer
from lbrynet.lbrynet_console.interfaces import ICommandHandlerFactory, ICommandHandler

log = logging.getLogger(__name__)


class CommandHandlerFactory(object):
    implements(ICommandHandlerFactory)
    short_help = "This should be overridden"
    full_help = "This should really be overridden"
    control_handler_class = None

    def __init__(self, *args):
        self.args = args

    def get_handler(self, *args):
        all_args = self.args + args
        return self.control_handler_class(*all_args)


class CommandHandler(object):
    implements(ICommandHandler)

    def __init__(self):
        self.finished_deferred = defer.Deferred()

    def handle_line(self):
        raise NotImplementedError()


class AddStream(CommandHandler):
    pass


class AddStreamFactory(CommandHandlerFactory):
    control_handler_class = AddStream
    short_help = "Pull from the network"
    full_help = "Pull from the network"