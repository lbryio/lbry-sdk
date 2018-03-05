#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Generate docs: python gen_api_docs.py
# See docs: pip install mkdocs; mkdocs serve
# Push docs: mkdocs build

import re
import inspect
import subprocess
import os
import sys
from lbrynet.daemon.Daemon import Daemon

import pip
installed_packages = [package.project_name for package in pip.get_installed_distributions()]

for package in ["mkdocs", "mkdocs-material"]:
    if package not in installed_packages:
        print "'" + package + "' is not installed"
        sys.exit(1)

try:
    from tabulate import tabulate
except ImportError:
    raise ImportError("tabulate is not installed")

INDENT = "    "
REQD_CMD_REGEX = r"\(.*?=<(?P<reqd>.*?)>\)"
OPT_CMD_REGEX = r"\[.*?=<(?P<opt>.*?)>\]"
CMD_REGEX = r"--.*?(?P<cmd>.*?)[=,\s,<]"
DOCS_BUILD_DIR = "docs_build"  # must match mkdocs.yml


def _cli_tabulate_options(_options_docstr, method):
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


def _api_tabulate_options(_options_docstr, method, reqd_matches, opt_matches):
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
                parts[0] = "'" + match[0] + "'"
            else:
                parts[0] = "'" + match[0] + "' (required)"

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


def _cli_doc(obj):
    docstr = (inspect.getdoc(obj) or '').strip()

    try:
        _usage_docstr, _docstr_after_options = docstr.split("Options:", 1)
        _options_docstr, _returns_docstr = _docstr_after_options.split("Returns:", 1)
    except(ValueError):
        print "Error: Ill formatted doc string for {}".format(obj)
        print "Please ensure that the docstring has all the three headings i.e. \"Usage:\""
        print "\"Options:\" and \"Returns:\" exactly as specified, including the colon"
        return "Error!"

    try:
        _options_docstr = _cli_tabulate_options(_options_docstr.strip(), obj)
    except Exception as e:
        print "Please make sure that the individual options are properly formatted"
        print "It should be strictly of the format:"
        print "--command_name=<command_name> : (type) desc"
        print e.message

    docstr = _usage_docstr + \
        "\nOptions:\n" + \
        _options_docstr + \
        "\nReturns:" + \
        _returns_docstr

    return docstr


def _api_doc(obj):
    docstr = (inspect.getdoc(obj) or '').strip()

    try:
        _desc, _docstr_after_desc = docstr.split("Usage:", 1)
        _usage_docstr, _docstr_after_options = _docstr_after_desc.split("Options:", 1)
        _options_docstr, _returns_docstr = _docstr_after_options.split("Returns:", 1)
    except(ValueError):
        print "Error: Ill formatted doc string for {}".format(obj)
        print "Please ensure that the docstring has all the three headings i.e. \"Usage:\""
        print "\"Options:\" and \"Returns:\" exactly as specified, including the colon"
        return "Error!"

    opt_matches = re.findall(OPT_CMD_REGEX, _usage_docstr)
    reqd_matches = re.findall(REQD_CMD_REGEX, _usage_docstr)

    try:
        _options_docstr = _api_tabulate_options(_options_docstr.strip(), obj, reqd_matches, opt_matches)
    except Exception as e:
        print "Please make sure that the individual options are properly formatted"
        print "It should be strictly of the format:"
        print "--command_name=<command_name> : (type) desc"
        print e.message

    docstr = _desc + \
        "Args:\n" + \
        _options_docstr + \
        "\nReturns:" + \
        _returns_docstr

    return docstr


def main():
    root_dir = os.path.dirname(os.path.dirname(__file__))
    build_dir = os.path.realpath(os.path.join(root_dir, DOCS_BUILD_DIR))
    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    api_doc_path = os.path.join(build_dir, 'index.md')
    cli_doc_path = os.path.join(build_dir, 'cli.md')

    _api_docs = ''
    _cli_docs = ''
    for method_name in sorted(Daemon.callable_methods.keys()):
        method = Daemon.callable_methods[method_name]
        _api_docs += '## ' + method_name + "\n\n```text\n" + _api_doc(method) + "\n```\n\n"
        _cli_docs += '## ' + method_name + "\n\n```text\n" + _cli_doc(method) + "\n```\n\n"

    _api_docs = "# LBRY JSON-RPC API Documentation\n\n" + _api_docs
    with open(api_doc_path, 'w+') as f:
        f.write(_api_docs)

    _cli_docs = "# LBRY JSON-RPC API Documentation\n\n" + _cli_docs
    with open(cli_doc_path, 'w+') as f:
        f.write(_cli_docs)

    try:
        subprocess.check_output("exec mkdocs build", cwd=root_dir, shell=True)
    except subprocess.CalledProcessError as e:
        print e.output
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main())
