.PHONY: dev lint idea clean

VENV_PYTHON:=$(shell pwd)/lbry-venv/bin/python

.DEFAULT: clean install

install: lbry-venv/bin/activate lbry-venv/bin/lbrynet lbry-venv/bin/torba

install-dev: install dev

dev: lbry-venv/bin/activate
	$(VENV_PYTHON) -m pip install mypy==0.701
	$(VENV_PYTHON) -m pip install coverage astroid pylint

lint: dev
	$(VENV_PYTHON) -m pylint lbry/lbry
	$(VENV_PYTHON) -m pylint --rcfile=torba/setup.cfg torba/torba
	$(VENV_PYTHON) -m mypy --ignore-missing-imports torba/torba

idea:
	mkdir -p .idea
	cp -r lbry/scripts/idea/* .idea

clean:
	- rm -rf lbry-venv

lbry-venv/bin/activate:
	virtualenv --python=python3.7 lbry-venv

lbry-venv/bin/lbrynet: lbry-venv/bin/activate lbry-venv/bin/torba
	$(VENV_PYTHON) -m pip install -e lbry/

lbry-venv/bin/torba: lbry-venv/bin/activate
	$(VENV_PYTHON) -m pip install -e torba/

