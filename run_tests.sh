#!/bin/bash

set -o xtrace

if [ -z "$@" ]; then
    TESTS=tests
else
    TESTS="$@"
fi

find -iname "*.pyc" -delete
PYTHONPATH=. trial $TESTS
