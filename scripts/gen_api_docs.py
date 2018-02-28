# -*- coding: utf-8 -*-

# Generate docs: python gen_api_docs.py
# See docs: pip install mkdocs; mkdocs serve
# Push docs: mkdocs build

import inspect
import sys
import re
import os.path as op
from tabulate import tabulate
from lbrynet.daemon.Daemon import Daemon

INDENT = "    "
REQD_CMD_REGEX = r"\(.*?=<(?P<reqd>.*?)>\)"
OPT_CMD_REGEX = r"\[.*?=<(?P<opt>.*?)>\]"
CMD_REGEX = r"--.*?(?P<cmd>.*?)[=,\s,<]"
DOCS_DIR = "docs_build"


def _tabulate_options(_options_docstr, method, reqd_matches, opt_matches):
    _option_list = []
    for line in _options_docstr.splitlines():
        if (line.strip().startswith("--")):
            # separates command name and description
            parts = line.split(":", 1)

            # checks whether the command is optional or required
            # and remove the cli type formatting and convert to
            # api style formatitng
            match = re.findall(CMD_REGEX, parts[0])

            if match[0] not in reqd_matches:
                parts[0] = "'" + match[0] + "' (optional)"
            else:
                parts[0] = "'" + match[0] + "'"

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

    # tabulate to make the options look pretty
    _options_docstr = ""
    for line in _options_docstr_no_indent.splitlines():
        _options_docstr += INDENT + line + '\n'

    return _options_docstr


def _doc(obj):
    docstr = (inspect.getdoc(obj) or '').strip()

    try:
        _desc, _docstr_after_desc = docstr.split("Usage:", 1)
        _usage_docstr, _docstr_after_options = _docstr_after_desc.split("Options:", 1)
        _options_docstr, _returns_docstr = _docstr_after_options.split("Returns:", 1)
    except(ValueError):
        print "Error: Ill formatted doc string for {}".format(obj)
        return "Error!"

    opt_matches = re.findall(OPT_CMD_REGEX, _usage_docstr)
    reqd_matches = re.findall(REQD_CMD_REGEX, _usage_docstr)

    _options_docstr = _tabulate_options(_options_docstr.strip(), obj, reqd_matches, opt_matches)

    docstr = _desc + \
        "Args:\n" + \
        _options_docstr + \
        "\nReturns:" + \
        _returns_docstr

    return docstr


def main():
    curdir = op.dirname(op.realpath(__file__))
    api_doc_path = op.realpath(op.join(curdir, '..', DOCS_DIR, 'index.md'))

    docs = ''
    for method_name in sorted(Daemon.callable_methods.keys()):
        method = Daemon.callable_methods[method_name]
        docs += '## ' + method_name + "\n\n```text\n" + _doc(method) + "\n```\n\n"

    docs = "# LBRY JSON-RPC API Documentation\n\n" + docs
    with open(api_doc_path, 'w+') as f:
        f.write(docs)


if __name__ == '__main__':
    sys.exit(main())
