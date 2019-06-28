.PHONY: venv create-venve clean-venv

install:
	cd torba && pip install -e .
	cd lbry && pip install -e .
	pip install mypy==0.701
	pip install coverage astroid pylint

lint:
	cd lbry && pylint lbry
	cd torba && pylint --rcfile=setup.cfg torba
	cd torba && mypy --ignore-missing-imports torba

idea:
	mkdir -p .idea
	cp -r lbry/scripts/idea/* .idea

VENV_NAME?=lbry-venv
VENV_PYTHON=$(shell pwd)/$(VENV_NAME)/bin/python

venv: clean-venv create-venv
	cd torba && $(VENV_PYTHON) -m pip install -e .
	cd lbry && $(VENV_PYTHON) -m pip install -e .
	$(VENV_PYTHON) -m pip install mypy==0.701
	$(VENV_PYTHON) -m pip install coverage astroid pylint

create-venv:
	virtualenv --python=python3.7 $(VENV_NAME)

clean-venv:
	- rm -rf $(VENV_NAME)
