import logging
from twisted.internet import defer

from lbrynet.core.Error import ComponentStartConditionNotMet

log = logging.getLogger(__name__)


class RegisteredConditions:
    conditions = {}


class RequiredConditionType(type):
    def __new__(mcs, name, bases, newattrs):
        klass = type.__new__(mcs, name, bases, newattrs)
        if name != "RequiredCondition":
            if klass.name in RegisteredConditions.conditions:
                raise SyntaxError("already have a component registered for \"%s\"" % klass.name)
            RegisteredConditions.conditions[klass.name] = klass
        return klass


class RequiredCondition(metaclass=RequiredConditionType):
    name = ""
    component = ""
    message = ""

    @staticmethod
    def evaluate(component):
        raise NotImplementedError()


class ComponentManager:
    default_component_classes = {}

    def __init__(self, reactor=None, analytics_manager=None, skip_components=None, **override_components):
        self.skip_components = skip_components or []

        self.reactor = reactor
        self.component_classes = {}
        self.components = set()
        self.analytics_manager = analytics_manager

        for component_name, component_class in self.default_component_classes.items():
            if component_name in override_components:
                component_class = override_components.pop(component_name)
            if component_name not in self.skip_components:
                self.component_classes[component_name] = component_class

        if override_components:
            raise SyntaxError("unexpected components: %s" % override_components)

        for component_class in self.component_classes.values():
            self.components.add(component_class(self))

    def evaluate_condition(self, condition_name):
        if condition_name not in RegisteredConditions.conditions:
            raise NameError(condition_name)
        condition = RegisteredConditions.conditions[condition_name]
        try:
            component = self.get_component(condition.component)
            result = condition.evaluate(component)
        except Exception:
            log.exception('failed to evaluate condition:')
            result = False
        return result, "" if result else condition.message

    def sort_components(self, reverse=False):
        """
        Sort components by requirements
        """
        steps = []
        staged = set()
        components = set(self.components)

        # components with no requirements
        step = []
        for component in set(components):
            if not component.depends_on:
                step.append(component)
                staged.add(component.component_name)
                components.remove(component)

        if step:
            step.sort()
            steps.append(step)

        while components:
            step = []
            to_stage = set()
            for component in set(components):
                reqs_met = 0
                for needed in component.depends_on:
                    if needed in staged:
                        reqs_met += 1
                if reqs_met == len(component.depends_on):
                    step.append(component)
                    to_stage.add(component.component_name)
                    components.remove(component)
            if step:
                step.sort()
                staged.update(to_stage)
                steps.append(step)
            elif components:
                raise ComponentStartConditionNotMet("Unresolved dependencies for: %s" % components)
        if reverse:
            steps.reverse()
        return steps

    @defer.inlineCallbacks
    def setup(self, **callbacks):
        """
        Start Components in sequence sorted by requirements

        :return: (defer.Deferred)
        """

        for component_name, cb in callbacks.items():
            if component_name not in self.component_classes:
                raise NameError("unknown component: %s" % component_name)
            if not callable(cb):
                raise ValueError("%s is not callable" % cb)

        def _setup(component):
            if component.component_name in callbacks:
                d = component._setup()
                d.addCallback(callbacks[component.component_name], component)
                return d
            return component._setup()

        stages = self.sort_components()
        for stage in stages:
            yield defer.DeferredList([_setup(component) for component in stage if not component.running])

    @defer.inlineCallbacks
    def stop(self):
        """
        Stop Components in reversed startup order

        :return: (defer.Deferred)
        """
        stages = self.sort_components(reverse=True)
        for stage in stages:
            yield defer.DeferredList([component._stop() for component in stage if component.running])

    def all_components_running(self, *component_names):
        """
        Check if components are running

        :return: (bool) True if all specified components are running
        """
        components = {component.component_name: component for component in self.components}
        for component in component_names:
            if component not in components:
                raise NameError("%s is not a known Component" % component)
            if not components[component].running:
                return False
        return True

    def get_components_status(self):
        """
        List status of all the components, whether they are running or not

        :return: (dict) {(str) component_name: (bool) True is running else False}
        """
        return {
            component.component_name: component.running
            for component in self.components
        }

    def get_component(self, component_name):
        for component in self.components:
            if component.component_name == component_name:
                return component.component
        raise NameError(component_name)
