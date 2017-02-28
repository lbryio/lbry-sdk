# -*- coding: utf-8 -*-

# Generate docs: python gen_api_docs.py
# See docs: pip install mkdocs; mkdocs serve
# Push docs: mkdocs gh-deploy

import inspect
import os.path as op
import re
import sys

from six import string_types
from lbrynet.lbrynet_daemon.Daemon import Daemon


def _name(obj):
    if hasattr(obj, '__name__'):
        return obj.__name__
    elif inspect.isdatadescriptor(obj):
        return obj.fget.__name__


def _anchor(name):
    anchor = name.lower().replace(' ', '-')
    anchor = re.sub(r'[^\w\- ]', '', anchor)
    return anchor


_docstring_header_pattern = re.compile(r'^([^\n]+)\n[\-\=]{3,}$', flags=re.MULTILINE)
_docstring_parameters_pattern = re.compile(r'^([^ \n]+) \: ([^\n]+)$', flags=re.MULTILINE)


def _replace_docstring_header(paragraph):
    """Process NumPy-like function docstrings."""

    # Replace Markdown headers in docstrings with light headers in bold.
    paragraph = re.sub(_docstring_header_pattern, r'*\1*', paragraph)
    paragraph = re.sub(_docstring_parameters_pattern, r'\n* `\1` (\2)\n', paragraph)
    return paragraph


def _doc(obj):
    docstr = (inspect.getdoc(obj) or '').strip()
    return _replace_docstring_header(docstr) if docstr and '---' in docstr else docstr


def _is_public(obj):
    name = _name(obj) if not isinstance(obj, string_types) else obj
    if name:
        return not name.startswith('_')
    else:
        return True


def _is_defined_in_package(obj, package):
    if isinstance(obj, property):
        obj = obj.fget
    mod = inspect.getmodule(obj)
    if mod and hasattr(mod, '__name__'):
        name = mod.__name__
        return name.split('.')[0] == package
    return True


def _iter_doc_members(obj, package=None):
    for _, member in inspect.getmembers(obj):
        if _is_public(member):
            if package is None or _is_defined_in_package(member, package):
                yield member


def _iter_methods(klass, package=None):
    for member in _iter_doc_members(klass, package):
        if inspect.isfunction(member) or inspect.ismethod(member):
            if inspect.isdatadescriptor(member):
                continue
            if _name(member).startswith('jsonrpc_'):
                yield member


def _link(name, anchor=None):
    return "[{name}](#{anchor})".format(name=name, anchor=anchor or _anchor(name))


def main():
    curdir = op.dirname(op.realpath(__file__))
    path = op.realpath(op.join(curdir, '..', 'docs', 'index.md'))

    klass = Daemon

    # toc = ''
    doc = ''
    # Table of contents
    for method in _iter_methods(klass):
        method_name = _name(method)[len('jsonrpc_'):]
        method_doc = _doc(method)
        if "DEPRECATED" in method_doc:
            continue
        # toc += '* ' + _link(method_name, _anchor(method_name)) + "\n"
        doc += '## ' + method_name + "\n\n```text\n" + method_doc + "\n```\n\n"

    text = "# LBRY JSON-RPC API Documentation\n\n" + doc

    with open(path, 'w+') as f:
        f.write(text)


if __name__ == '__main__':
    sys.exit(main())
