import logging
from twisted.internet import defer
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

    @property
    def running(self):
        return self._running

    def start(self):
        raise NotImplementedError()  # override

    def stop(self):
        raise NotImplementedError()  # override

    def component(self):
        raise NotImplementedError()  # override

    @defer.inlineCallbacks
    def _setup(self):
        try:
            result = yield defer.maybeDeferred(self.start)
            self._running = True
            defer.returnValue(result)
        except Exception as err:
            log.exception("Error setting up %s", self.component_name or self.__class__.__name__)
            raise err

    @defer.inlineCallbacks
    def _stop(self):
        try:
            result = yield defer.maybeDeferred(self.stop)
            self._running = False
            defer.returnValue(result)
        except Exception as err:
            log.exception("Error stopping %s", self.__class__.__name__)
            raise err
