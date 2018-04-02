import logging
from twisted.internet import defer

log = logging.getLogger(__name__)


class ComponentManager(object):
    components = set()

    @classmethod
    def sort_components(cls, reverse=False):
        """
        Sort components by requirements
        """
        steps = []
        staged = set()
        components = set(cls.components)

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

    @classmethod
    @defer.inlineCallbacks
    def setup(cls, **callbacks):
        """
        Start Components in sequence sorted by requirements

        :return: (defer.Deferred)
        """
        for component_name, cb in callbacks.iteritems():
            if not callable(cb):
                raise ValueError("%s is not callable" % cb)
            cls.get_component(component_name)

        def _setup(component):
            if component.component_name in callbacks:
                d = component._setup()
                d.addCallback(callbacks[component.component_name])
                return d
            return component.setup()

        stages = cls.sort_components()
        for stage in stages:
            yield defer.DeferredList([_setup(component) for component in stage])

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        """
        Stop Components in reversed startup order

        :return: (defer.Deferred)
        """
        stages = cls.sort_components(reverse=True)
        for stage in stages:
            yield defer.DeferredList([component._stop() for component in stage])

    @classmethod
    def all_components_running(cls, *component_names):
        """
        Check if components are running

        :return: (bool) True if all specified components are running
        """
        components = {component.component_name: component for component in cls.components}
        for component in component_names:
            if component not in components:
                raise NameError("%s is not a known Component" % component)
            if not components[component].running:
                return False
        return True

    @classmethod
    def get_component(cls, component_name):
        for component in cls.components:
            if component.component_name == component_name:
                return component
        raise NameError(component_name)
