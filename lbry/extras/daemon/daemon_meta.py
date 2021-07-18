#!/usr/bin/env python3
"""
Meta class definition for the Daemon class, and auxiliary methods.
"""
import json
import re
from functools import wraps
from typing import Callable, List, Optional

from lbry.error import (ComponentsNotStartedError,
                        ComponentStartConditionNotMetError)

DEFAULT_PAGE_SIZE = 20
VALID_FULL_CLAIM_ID = re.compile('[0-9a-fA-F]{40}')


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


def paginate_list(items: List, page: Optional[int], page_size: Optional[int]):
    page = max(1, page or 1)
    page_size = max(1, page_size or DEFAULT_PAGE_SIZE)
    total_items = len(items)
    offset = page_size * (page - 1)
    subitems = []
    if offset <= total_items:
        subitems = items[offset:offset+page_size]
    return {
        "items": subitems,
        "total_pages": int((total_items + (page_size - 1)) / page_size),
        "total_items": total_items,
        "page": page, "page_size": page_size
    }


async def paginate_rows(get_records: Callable, get_record_count: Optional[Callable],
                        page: Optional[int], page_size: Optional[int], **constraints):
    page = max(1, page or 1)
    page_size = max(1, page_size or DEFAULT_PAGE_SIZE)
    constraints.update({
        "offset": page_size * (page - 1),
        "limit": page_size
    })
    items = await get_records(**constraints)
    result = {"items": items, "page": page, "page_size": page_size}
    if get_record_count is not None:
        total_items = await get_record_count(**constraints)
        result["total_pages"] = int((total_items + (page_size - 1)) / page_size)
        result["total_items"] = total_items
    return result
