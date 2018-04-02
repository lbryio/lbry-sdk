import logging
from twisted.internet import defer
from ComponentManager import ComponentManager

log = logging.getLogger(__name__)


class ComponentType(type):
    def __new__(mcs, name, bases, newattrs):
        klass = type.__new__(mcs, name, bases, newattrs)
        if name != "Component":
            ComponentManager.components.add(klass)
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
    running = False

    @classmethod
    def setup(cls):
        raise NotImplementedError()  # override

    @classmethod
    def stop(cls):
        raise NotImplementedError()  # override

    @classmethod
    @defer.inlineCallbacks
    def _setup(cls):
        try:
            result = yield defer.maybeDeferred(cls.setup)
            cls.running = True
            defer.returnValue(result)
        except Exception as err:
            log.exception("Error setting up %s", cls.component_name or cls.__name__)
            raise err

    @classmethod
    @defer.inlineCallbacks
    def _stop(cls):
        try:
            result = yield defer.maybeDeferred(cls.stop)
            cls.running = False
            defer.returnValue(result)
        except Exception as err:
            log.exception("Error stopping %s", cls.__name__)
            raise err
