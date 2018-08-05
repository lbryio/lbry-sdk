import logging
from twisted.internet import defer
from twisted._threads import AlreadyQuit
from lbrynet.core.utils import maybe_deferred_trap_and_trace
from ComponentManager import ComponentManager

log = logging.getLogger(__name__)


class ComponentType(type):
    def __new__(mcs, name, bases, newattrs):
        klass = type.__new__(mcs, name, bases, newattrs)
        if name != "Component":
            ComponentManager.default_component_classes[klass.component_name] = klass
        return klass


class Component(object):
    """
    lbrynet-daemon component helper

    Inheriting classes will be automatically registered with the ComponentManager and must implement setup and stop
    methods
    """

    __metaclass__ = ComponentType
    depends_on = []
    component_name = None

    def __init__(self, component_manager):
        self.component_manager = component_manager
        self._running = False

    def __lt__(self, other):
        return self.component_name < other.component_name

    @property
    def running(self):
        return self._running

    def get_status(self):
        return

    def start(self):
        raise NotImplementedError()

    def stop(self):
        raise NotImplementedError()

    @property
    def component(self):
        raise NotImplementedError()

    def _setup(self):
        def set_running(result):
            self._running = True
            return result

        def handle_error(err):
            log.error("Error setting up %s\n%s", self.component_name or self.__class__.__name__, err.getTraceback())

        return maybe_deferred_trap_and_trace(
            (defer.CancelledError, AlreadyQuit), set_running, handle_error
        )(self.start)()

    def _stop(self):
        def set_running(result):
            self._running = False
            return result

        def handle_error(err):
            log.error("Error stopping %s\n%s", self.component_name or self.__class__.__name__, err.getTraceback())

        return maybe_deferred_trap_and_trace(
            (defer.CancelledError, AlreadyQuit), set_running, handle_error
        )(self.stop)()
