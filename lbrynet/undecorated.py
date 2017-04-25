# -*- coding: utf-8 -*-
# Copyright 2016-2017 Ionuț Arțăriși <ionut@artarisi.eu>

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# This came from https://github.com/mapleoin/undecorated

from inspect import isfunction, ismethod, isclass

__version__ = '0.3.0'


def undecorated(o):
    """Remove all decorators from a function, method or class"""
    # class decorator
    if isinstance(o, type):
        return o

    try:
        # python2
        closure = o.func_closure
    except AttributeError:
        pass

    # try:
    #     # python3
    #     closure = o.__closure__
    # except AttributeError:
    #     return

    if closure:
        for cell in closure:
            # avoid infinite recursion
            if cell.cell_contents is o:
                continue

            # check if the contents looks like a decorator; in that case
            # we need to go one level down into the dream, otherwise it
            # might just be a different closed-over variable, which we
            # can ignore.

            # Note: this favors supporting decorators defined without
            # @wraps to the detriment of function/method/class closures
            if looks_like_a_decorator(cell.cell_contents):
                undecd = undecorated(cell.cell_contents)
                if undecd:
                    return undecd
    return o


def looks_like_a_decorator(a):
    return isfunction(a) or ismethod(a) or isclass(a)
