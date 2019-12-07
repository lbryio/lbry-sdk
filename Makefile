install:
	pip install https://github.com/rogerbinns/apsw/releases/download/3.30.1-r1/apsw-3.30.1-r1.zip \
		--global-option=fetch \
		--global-option=--version --global-option=3.30.1 --global-option=--all \
		--global-option=build --global-option=--enable --global-option=fts5
	cd torba && pip install -e .
	cd lbry && pip install -e .
	pip install mypy==0.701
	pip install coverage astroid pylint

lint:
	cd lbry && pylint lbry
	cd torba && pylint --rcfile=setup.cfg torba
	cd torba && mypy --ignore-missing-imports torba

test:
	cd lbry && tox
	cd torba && tox

idea:
	mkdir -p .idea
	cp -r lbry/scripts/idea/* .idea
