# Copyright (c) 2018, Neil Booth
#
# All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

__all__ = ()


import asyncio
from collections import namedtuple
from functools import partial
import inspect


def normalize_corofunc(corofunc, args):
    if asyncio.iscoroutine(corofunc):
        if args != ():
            raise ValueError('args cannot be passed with a coroutine')
        return corofunc
    return corofunc(*args)


def is_async_call(func):
    '''inspect.iscoroutinefunction that looks through partials.'''
    while isinstance(func, partial):
        func = func.func
    return inspect.iscoroutinefunction(func)


# other_params: None means cannot be called with keyword arguments only
# any means any name is good
SignatureInfo = namedtuple('SignatureInfo', 'min_args max_args '
                           'required_names other_names')


def signature_info(func):
    params = inspect.signature(func).parameters
    min_args = max_args = 0
    required_names = []
    other_names = []
    no_names = False
    for p in params.values():
        if p.kind == p.POSITIONAL_OR_KEYWORD:
            max_args += 1
            if p.default is p.empty:
                min_args += 1
                required_names.append(p.name)
            else:
                other_names.append(p.name)
        elif p.kind == p.KEYWORD_ONLY:
            other_names.append(p.name)
        elif p.kind == p.VAR_POSITIONAL:
            max_args = None
        elif p.kind == p.VAR_KEYWORD:
            other_names = any
        elif p.kind == p.POSITIONAL_ONLY:
            max_args += 1
            if p.default is p.empty:
                min_args += 1
            no_names = True

    if no_names:
        other_names = None

    return SignatureInfo(min_args, max_args, required_names, other_names)


class Concurrency(object):

    def __init__(self, max_concurrent):
        self._require_non_negative(max_concurrent)
        self._max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)

    def _require_non_negative(self, value):
        if not isinstance(value, int) or value < 0:
            raise RuntimeError('concurrency must be a natural number')

    @property
    def max_concurrent(self):
        return self._max_concurrent

    async def set_max_concurrent(self, value):
        self._require_non_negative(value)
        diff = value - self._max_concurrent
        self._max_concurrent = value
        if diff >= 0:
            for _ in range(diff):
                self.semaphore.release()
        else:
            for _ in range(-diff):
                await self.semaphore.acquire()


def check_task(logger, task):
    if not task.cancelled():
        try:
            task.result()
        except Exception:
            logger.error('task crashed: %r', task, exc_info=True)
