# The code below is mostly my own but based on the interfaces of the
# curio library by David Beazley.  I'm considering switching to using
# curio.  In the mean-time this is an attempt to provide a similar
# clean, pure-async interface and move away from direct
# framework-specific dependencies.  As asyncio differs in its design
# it is not possible to provide identical semantics.
#
# The curio library is distributed under the following licence:
#
# Copyright (C) 2015-2017
# David Beazley (Dabeaz LLC)
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of the David Beazley or Dabeaz LLC may be used to
#   endorse or promote products derived from this software without
#   specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import logging
import asyncio
from asyncio import (
    CancelledError, get_event_loop, Queue, Event, Lock, Semaphore,
    sleep, Task
)
from collections import deque
from contextlib import suppress
from functools import partial

from .util import normalize_corofunc, check_task


__all__ = (
    'Queue', 'Event', 'Lock', 'Semaphore', 'sleep', 'CancelledError',
    'run_in_thread', 'spawn', 'spawn_sync', 'TaskGroup',
    'TaskTimeout', 'TimeoutCancellationError', 'UncaughtTimeoutError',
    'timeout_after', 'timeout_at', 'ignore_after', 'ignore_at',
)


async def run_in_thread(func, *args):
    '''Run a function in a separate thread, and await its completion.'''
    return await get_event_loop().run_in_executor(None, func, *args)


async def spawn(coro, *args, loop=None, report_crash=True):
    return spawn_sync(coro, *args, loop=loop, report_crash=report_crash)


def spawn_sync(coro, *args, loop=None, report_crash=True):
    coro = normalize_corofunc(coro, args)
    loop = loop or get_event_loop()
    task = loop.create_task(coro)
    if report_crash:
        task.add_done_callback(partial(check_task, logging))
    return task


class TaskGroup(object):
    '''A class representing a group of executing tasks. tasks is an
    optional set of existing tasks to put into the group. New tasks
    can later be added using the spawn() method below. wait specifies
    the policy used for waiting for tasks. See the join() method
    below. Each TaskGroup is an independent entity. Task groups do not
    form a hierarchy or any kind of relationship to other previously
    created task groups or tasks. Moreover, Tasks created by the top
    level spawn() function are not placed into any task group. To
    create a task in a group, it should be created using
    TaskGroup.spawn() or explicitly added using TaskGroup.add_task().

    completed attribute: the first task that completed with a result
    in the group.  Takes into account the wait option used in the
    TaskGroup constructor (but not in the join method)`.
    '''

    def __init__(self, tasks=(), *, wait=all):
        if wait not in (any, all, object):
            raise ValueError('invalid wait argument')
        self._done = deque()
        self._pending = set()
        self._wait = wait
        self._done_event = Event()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._closed = False
        self.completed = None
        for task in tasks:
            self._add_task(task)

    def _add_task(self, task):
        '''Add an already existing task to the task group.'''
        if hasattr(task, '_task_group'):
            raise RuntimeError('task is already part of a group')
        if self._closed:
            raise RuntimeError('task group is closed')
        task._task_group = self
        if task.done():
            self._done.append(task)
        else:
            self._pending.add(task)
            task.add_done_callback(self._on_done)

    def _on_done(self, task):
        task._task_group = None
        self._pending.remove(task)
        self._done.append(task)
        self._done_event.set()
        if self.completed is None:
            if not task.cancelled() and not task.exception():
                if self._wait is object and task.result() is None:
                    pass
                else:
                    self.completed = task

    async def spawn(self, coro, *args):
        '''Create a new task that’s part of the group. Returns a Task
        instance.
        '''
        task = await spawn(coro, *args, report_crash=False)
        self._add_task(task)
        return task

    async def add_task(self, task):
        '''Add an already existing task to the task group.'''
        self._add_task(task)

    async def next_done(self):
        '''Returns the next completed task.  Returns None if no more tasks
        remain. A TaskGroup may also be used as an asynchronous iterator.
        '''
        if not self._done and self._pending:
            self._done_event.clear()
            await self._done_event.wait()
        if self._done:
            return self._done.popleft()
        return None

    async def next_result(self):
        '''Returns the result of the next completed task. If the task failed
        with an exception, that exception is raised. A RuntimeError
        exception is raised if this is called when no remaining tasks
        are available.'''
        task = await self.next_done()
        if not task:
            raise RuntimeError('no tasks remain')
        return task.result()

    async def join(self):
        '''Wait for tasks in the group to terminate according to the wait
        policy for the group.

        If the join() operation itself is cancelled, all remaining
        tasks in the group are also cancelled.

        If a TaskGroup is used as a context manager, the join() method
        is called on context-exit.

        Once join() returns, no more tasks may be added to the task
        group.  Tasks can be added while join() is running.
        '''
        def errored(task):
            return not task.cancelled() and task.exception()

        try:
            if self._wait in (all, object):
                while True:
                    task = await self.next_done()
                    if task is None:
                        return
                    if errored(task):
                        break
                    if self._wait is object:
                        if task.cancelled() or task.result() is not None:
                            return
            else:  # any
                task = await self.next_done()
                if task is None or not errored(task):
                    return
        finally:
            await self.cancel_remaining()

        if errored(task):
            raise task.exception()

    async def cancel_remaining(self):
        '''Cancel all remaining tasks.'''
        self._closed = True
        for task in list(self._pending):
            task.cancel()
            with suppress(CancelledError):
                await task

    def closed(self):
        return self._closed

    def __aiter__(self):
        return self

    async def __anext__(self):
        task = await self.next_done()
        if task:
            return task
        raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type:
            await self.cancel_remaining()
        else:
            await self.join()


class TaskTimeout(CancelledError):

    def __init__(self, secs):
        self.secs = secs

    def __str__(self):
        return f'task timed out after {self.args[0]}s'


class TimeoutCancellationError(CancelledError):
    pass


class UncaughtTimeoutError(Exception):
    pass


def _set_new_deadline(task, deadline):
    def timeout_task():
        # Unfortunately task.cancel is all we can do with asyncio
        task.cancel()
        task._timed_out = deadline
    task._deadline_handle = task._loop.call_at(deadline, timeout_task)


def _set_task_deadline(task, deadline):
    deadlines = getattr(task, '_deadlines', [])
    if deadlines:
        if deadline < min(deadlines):
            task._deadline_handle.cancel()
            _set_new_deadline(task, deadline)
    else:
        _set_new_deadline(task, deadline)
    deadlines.append(deadline)
    task._deadlines = deadlines
    task._timed_out = None


def _unset_task_deadline(task):
    deadlines = task._deadlines
    timed_out_deadline = task._timed_out
    uncaught = timed_out_deadline not in deadlines
    task._deadline_handle.cancel()
    deadlines.pop()
    if deadlines:
        _set_new_deadline(task, min(deadlines))
    return timed_out_deadline, uncaught


class TimeoutAfter(object):

    def __init__(self, deadline, *, ignore=False, absolute=False):
        self._deadline = deadline
        self._ignore = ignore
        self._absolute = absolute
        self.expired = False

    async def __aenter__(self):
        task = asyncio.current_task()
        loop_time = task._loop.time()
        if self._absolute:
            self._secs = self._deadline - loop_time
        else:
            self._secs = self._deadline
            self._deadline += loop_time
        _set_task_deadline(task, self._deadline)
        self.expired = False
        self._task = task
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        timed_out_deadline, uncaught = _unset_task_deadline(self._task)
        if exc_type not in (CancelledError, TaskTimeout,
                            TimeoutCancellationError):
            return False
        if timed_out_deadline == self._deadline:
            self.expired = True
            if self._ignore:
                return True
            raise TaskTimeout(self._secs) from None
        if timed_out_deadline is None:
            assert exc_type is CancelledError
            return False
        if uncaught:
            raise UncaughtTimeoutError('uncaught timeout received')
        if exc_type is TimeoutCancellationError:
            return False
        raise TimeoutCancellationError(timed_out_deadline) from None


async def _timeout_after_func(seconds, absolute, coro, args):
    coro = normalize_corofunc(coro, args)
    async with TimeoutAfter(seconds, absolute=absolute):
        return await coro


def timeout_after(seconds, coro=None, *args):
    '''Execute the specified coroutine and return its result. However,
    issue a cancellation request to the calling task after seconds
    have elapsed.  When this happens, a TaskTimeout exception is
    raised.  If coro is None, the result of this function serves
    as an asynchronous context manager that applies a timeout to a
    block of statements.

    timeout_after() may be composed with other timeout_after()
    operations (i.e., nested timeouts).  If an outer timeout expires
    first, then TimeoutCancellationError is raised instead of
    TaskTimeout.  If an inner timeout expires and fails to properly
    TaskTimeout, a UncaughtTimeoutError is raised in the outer
    timeout.

    '''
    if coro:
        return _timeout_after_func(seconds, False, coro, args)

    return TimeoutAfter(seconds)


def timeout_at(clock, coro=None, *args):
    '''Execute the specified coroutine and return its result. However,
    issue a cancellation request to the calling task after seconds
    have elapsed.  When this happens, a TaskTimeout exception is
    raised.  If coro is None, the result of this function serves
    as an asynchronous context manager that applies a timeout to a
    block of statements.

    timeout_after() may be composed with other timeout_after()
    operations (i.e., nested timeouts).  If an outer timeout expires
    first, then TimeoutCancellationError is raised instead of
    TaskTimeout.  If an inner timeout expires and fails to properly
    TaskTimeout, a UncaughtTimeoutError is raised in the outer
    timeout.

    '''
    if coro:
        return _timeout_after_func(clock, True, coro, args)

    return TimeoutAfter(clock, absolute=True)


async def _ignore_after_func(seconds, absolute, coro, args, timeout_result):
    coro = normalize_corofunc(coro, args)
    async with TimeoutAfter(seconds, absolute=absolute, ignore=True):
        return await coro

    return timeout_result


def ignore_after(seconds, coro=None, *args, timeout_result=None):
    '''Execute the specified coroutine and return its result. Issue a
    cancellation request after seconds have elapsed. When a timeout
    occurs, no exception is raised. Instead, timeout_result is
    returned.

    If coro is None, the result is an asynchronous context manager
    that applies a timeout to a block of statements. For the context
    manager case, the resulting context manager object has an expired
    attribute set to True if time expired.

    Note: ignore_after() may also be composed with other timeout
    operations. TimeoutCancellationError and UncaughtTimeoutError
    exceptions might be raised according to the same rules as for
    timeout_after().
    '''
    if coro:
        return _ignore_after_func(seconds, False, coro, args, timeout_result)

    return TimeoutAfter(seconds, ignore=True)


def ignore_at(clock, coro=None, *args, timeout_result=None):
    '''
    Stop the enclosed task or block of code at an absolute
    clock value. Same usage as ignore_after().
    '''
    if coro:
        return _ignore_after_func(clock, True, coro, args, timeout_result)

    return TimeoutAfter(clock, absolute=True, ignore=True)
