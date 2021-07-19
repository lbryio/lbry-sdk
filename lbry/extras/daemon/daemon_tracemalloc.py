#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basic class with tracemalloc methods for the Daemon class (JSON-RPC server).
"""
import linecache
import os
import tracemalloc

from lbry.extras.daemon.daemon_meta import JSONRPCServerType


class Daemon_tracemalloc(metaclass=JSONRPCServerType):
    def jsonrpc_tracemalloc_enable(self):  # pylint: disable=no-self-use
        """
        Enable tracemalloc memory tracing

        Usage:
            jsonrpc_tracemalloc_enable

        Options:
            None

        Returns:
            (bool) is it tracing?
        """
        tracemalloc.start()
        return tracemalloc.is_tracing()

    def jsonrpc_tracemalloc_disable(self):  # pylint: disable=no-self-use
        """
        Disable tracemalloc memory tracing

        Usage:
            jsonrpc_tracemalloc_disable

        Options:
            None

        Returns:
            (bool) is it tracing?
        """
        tracemalloc.stop()
        return tracemalloc.is_tracing()

    def jsonrpc_tracemalloc_top(self, items: int = 10):  # pylint: disable=no-self-use
        """
        Show most common objects, the place that created them and their size.

        Usage:
            jsonrpc_tracemalloc_top [(<items> | --items=<items>)]

        Options:
            --items=<items>               : (int) maximum items to return, from the most common

        Returns:
            (dict) dictionary containing most common objects in memory
            {
                "line": (str) filename and line number where it was created,
                "code": (str) code that created it,
                "size": (int) size in bytes, for each "memory block",
                "count" (int) number of memory blocks
            }
        """
        if not tracemalloc.is_tracing():
            raise Exception("Enable tracemalloc first! See 'tracemalloc set' command.")
        stats = tracemalloc.take_snapshot().filter_traces((
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, "<unknown>"),
            # tracemalloc and linecache here use some memory, but thats not relevant
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, linecache.__file__),
        )).statistics('lineno', True)
        results = []
        for stat in stats:
            frame = stat.traceback[0]
            filename = os.sep.join(frame.filename.split(os.sep)[-2:])
            line = linecache.getline(frame.filename, frame.lineno).strip()
            results.append({
                "line": f"{filename}:{frame.lineno}",
                "code": line,
                "size": stat.size,
                "count": stat.count
            })
            if len(results) == items:
                break
        return results
