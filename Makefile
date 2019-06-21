install:
	cd torba && pip install -e .
	cd lbry && pip install -e .

lint:
	cd lbry && pylint lbry
	cd torba && pylint --rcfile=setup.cfg torba
	cd torba && mypy --ignore-missing-imports torba
