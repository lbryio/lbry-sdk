# -*- coding: utf-8 -*-

# Generate docs: python gen_api_docs.py
# See docs: pip install mkdocs; mkdocs serve
# Push docs: mkdocs gh-deploy

import inspect
import os.path as op
import re
import sys

from lbrynet.daemon.Daemon import Daemon


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
    return _replace_docstring_header(docstr)


def _link(name, anchor=None):
    return "[{name}](#{anchor})".format(name=name, anchor=anchor or _anchor(name))


def main():
    curdir = op.dirname(op.realpath(__file__))
    cli_doc_path = op.realpath(op.join(curdir, '..', 'docs', 'cli.md'))

    # toc = ''
    doc = ''
    # Table of contents
    for method_name in sorted(Daemon.callable_methods.keys()):
        method = Daemon.callable_methods[method_name]
        # toc += '* ' + _link(method_name, _anchor(method_name)) + "\n"
        doc += '## ' + method_name + "\n\n```text\n" + _doc(method) + "\n```\n\n"

    text = "# LBRY Command Line Documentation\n\n" + doc
    with open(cli_doc_path, 'w+') as f:
        f.write(text)


if __name__ == '__main__':
    sys.exit(main())
