import logging
from twisted.internet import defer

log = logging.getLogger(__name__)


class ComponentManager(object):
    default_component_classes = {}
    # analytics_manager = None

    def __init__(self, analytics_manager=None, **override_components):
        self.component_classes = {}
        self.components = set()
        self.analytics_manager = analytics_manager

        for component_name, component_class in self.default_component_classes.iteritems():
            if component_name in override_components:
                component_class = override_components.pop(component_name)
            self.component_classes[component_name] = component_class

        if override_components:
            raise SyntaxError("unexpected components: %s" % override_components)

        for component_class in self.component_classes.itervalues():
            self.components.add(component_class(self))

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
                staged.update(to_stage)
                steps.append(step)
            elif components:
                raise SyntaxError("components cannot be started: %s" % components)
        if reverse:
            steps.reverse()
        return steps

    @defer.inlineCallbacks
    def setup(self, **callbacks):
        """
        Start Components in sequence sorted by requirements

        :return: (defer.Deferred)
        """

        for component_name, cb in callbacks.iteritems():
            if component_name not in self.component_classes:
                raise NameError("unknown component: %s" % component_name)
            if not callable(cb):
                raise ValueError("%s is not callable" % cb)

        def _setup(component):
            if component.component_name in callbacks:
                d = component._setup()
                d.addCallback(callbacks[component.component_name])
                return d
            return component._setup()

        stages = self.sort_components()
        for stage in stages:
            yield defer.DeferredList([_setup(component) for component in stage])

    @defer.inlineCallbacks
    def stop(self):
        """
        Stop Components in reversed startup order

        :return: (defer.Deferred)
        """
        stages = self.sort_components(reverse=True)
        for stage in stages:
            yield defer.DeferredList([component._stop() for component in stage])

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

    def get_component(self, component_name):
        for component in self.components:
            if component.component_name == component_name:
                return component
        raise NameError(component_name)
