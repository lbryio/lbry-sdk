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
from collections import deque
from contextlib import suppress


__all__ = 'TaskGroup',


class TaskGroup:
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
        self._done_event = asyncio.Event()
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
        task = asyncio.create_task(coro)
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
            with suppress(asyncio.CancelledError):
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
