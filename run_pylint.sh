#! /bin/bash


# Ignoring distutils because: https://github.com/PyCQA/pylint/issues/73
# TODO: as code quality improves, make pylint be more strict
pylint -E --disable=inherit-non-class --disable=no-member \
       --ignored-modules=distutils \
       --enable=unused-import \
       --enable=bad-whitespace \
       --enable=line-too-long \
       --enable=trailing-whitespace \
       --enable=missing-final-newline \
       lbrynet $@
