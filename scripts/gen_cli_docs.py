# -*- coding: utf-8 -*-

# Generate docs: python gen_cli_docs.py
# See docs: pip install mkdocs; mkdocs serve
# Push docs: mkdocs build

import inspect
import os.path as op
import sys
from tabulate import tabulate
from lbrynet.daemon.Daemon import Daemon

INDENT = "    "
DOCS_DIR = "docs_build"


def _tabulate_options(_options_docstr, method):
    _option_list = []
    for line in _options_docstr.splitlines():
        if (line.strip().startswith("--")):
            # separates command name and description
            parts = line.split(":", 1)
            # separates command type(in brackets) and description
            new_parts = parts[1].lstrip().split(" ", 1)
        else:
            parts = [line]

        # len will be 2 when there's cmd name and description
        if len(parts) == 2:
            _option_list.append([parts[0], ":", new_parts[0], new_parts[1]])
        # len will be 1 when there's continuation of multiline description in the next line
        # check `blob_announce`'s `stream_hash` command
        elif len(parts) == 1:
            _option_list.append([None, None, None, parts[0]])
        else:
            print "Error: Ill formatted doc string for {}".format(method)
            print "Error causing line: {}".format(line)

    # tabulate to make the options look pretty
    _options_docstr_no_indent = tabulate(_option_list, missingval="", tablefmt="plain")

    # Indent the options properly
    _options_docstr = ""
    for line in _options_docstr_no_indent.splitlines():
        _options_docstr += INDENT + line + '\n'

    return _options_docstr


def _doc(obj):
    docstr = (inspect.getdoc(obj) or '').strip()

    try:
        _usage_docstr, _docstr_after_options = docstr.split("Options:", 1)
        _options_docstr, _returns_docstr = _docstr_after_options.split("Returns:", 1)
    except(ValueError):
        print "Error: Ill formatted doc string for {}".format(obj)
        return "Error!"

    _options_docstr = _tabulate_options(_options_docstr.strip(), obj)

    docstr = _usage_docstr + \
        "\nOptions:\n" + \
        _options_docstr + \
        "\nReturns:" + \
        _returns_docstr

    return docstr


def main():
    curdir = op.dirname(op.realpath(__file__))
    cli_doc_path = op.realpath(op.join(curdir, '..', DOCS_DIR, 'cli.md'))

    docs = ''
    for method_name in sorted(Daemon.callable_methods.keys()):
        method = Daemon.callable_methods[method_name]
        docs += '## ' + method_name + "\n\n```text\n" + _doc(method) + "\n```\n\n"

    docs = "# LBRY Command Line Documentation\n\n" + docs
    with open(cli_doc_path, 'w+') as f:
        f.write(docs)


if __name__ == '__main__':
    sys.exit(main())
