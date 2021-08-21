import logging
import asyncio
from lbry.conf import Config
from lbry.error import ComponentStartConditionNotMetError
from lbry.dht.peer import PeerManager

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

    def __init__(self, conf: Config, analytics_manager=None, skip_components=None,
                 peer_manager=None, **override_components):
        self.conf = conf
        self.skip_components = skip_components or []
        self.loop = asyncio.get_event_loop()
        self.analytics_manager = analytics_manager
        self.component_classes = {}
        self.components = set()
        self.started = asyncio.Event()
        self.peer_manager = peer_manager or PeerManager(asyncio.get_event_loop_policy().get_event_loop())

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
                raise ComponentStartConditionNotMetError(components)
        if reverse:
            steps.reverse()
        return steps

    async def start(self):
        """ Start Components in sequence sorted by requirements """
        for stage in self.sort_components():
            needing_start = [
                component._setup() for component in stage if not component.running
            ]
            if needing_start:
                await asyncio.wait(needing_start)
        self.started.set()

    async def stop(self):
        """
        Stop Components in reversed startup order
        """
        stages = self.sort_components(reverse=True)
        for stage in stages:
            needing_stop = [
                component._stop() for component in stage if component.running
            ]
            if needing_stop:
                await asyncio.wait(needing_stop)

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

    def get_actual_component(self, component_name):
        for component in self.components:
            if component.component_name == component_name:
                return component
        raise NameError(component_name)

    def get_component(self, component_name):
        return self.get_actual_component(component_name).component

    def has_component(self, component_name):
        return any(component for component in self.components if component_name == component.component_name)
