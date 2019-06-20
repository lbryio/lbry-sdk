install:
	cd torba && pip install -e .
	cd lbry && pip install -e .

lint:
	cd torba && pylint --rcfile=setup.cfg torba
	cd torba && mypy --ignore-missing-imports torba
	cd lbry && pylint lbrynet
