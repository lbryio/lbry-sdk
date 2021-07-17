#!/usr/bin/env python3
"""
Meta class definition for the Daemon class, and auxiliary methods.
"""
import json
from functools import wraps

from lbry.error import (ComponentsNotStartedError,
                        ComponentStartConditionNotMetError)


class JSONRPCServerType(type):
    def __new__(mcs, name, bases, newattrs):
        klass = type.__new__(mcs, name, bases, newattrs)
        klass.callable_methods = {}
        klass.deprecated_methods = {}

        for methodname in dir(klass):
            if methodname.startswith("jsonrpc_"):
                method = getattr(klass, methodname)
                if not hasattr(method, '_deprecated'):
                    klass.callable_methods.update({methodname.split("jsonrpc_")[1]: method})
                else:
                    klass.deprecated_methods.update({methodname.split("jsonrpc_")[1]: method})
        return klass


def requires(*components, **conditions):
    if conditions and ["conditions"] != list(conditions.keys()):
        raise SyntaxError("invalid conditions argument")
    condition_names = conditions.get("conditions", [])

    def _wrap(method):
        @wraps(method)
        def _inner(*args, **kwargs):
            component_manager = args[0].component_manager
            for condition_name in condition_names:
                condition_result, err_msg = component_manager.evaluate_condition(condition_name)
                if not condition_result:
                    raise ComponentStartConditionNotMetError(err_msg)
            if not component_manager.all_components_running(*components):
                raise ComponentsNotStartedError(
                    f"the following required components have not yet started: {json.dumps(components)}"
                )
            return method(*args, **kwargs)

        return _inner

    return _wrap


def deprecated(new_command=None):
    def _deprecated_wrapper(f):
        f.new_command = new_command
        f._deprecated = True
        return f

    return _deprecated_wrapper
