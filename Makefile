.PHONY: install tools lint test idea

install:
	CFLAGS="-DSQLITE_MAX_VARIABLE_NUMBER=2500000" pip install -U https://github.com/rogerbinns/apsw/releases/download/3.30.1-r1/apsw-3.30.1-r1.zip \
		--global-option=fetch \
		--global-option=--version --global-option=3.30.1 --global-option=--all \
		--global-option=build --global-option=--enable --global-option=fts5
	cd lbry && pip install -e .

tools:
	pip install mypy==0.701
	pip install coverage astroid pylint

lint:
	cd lbry && pylint --rcfile=setup.cfg lbry
	#cd lbry && mypy --ignore-missing-imports lbry

test:
	cd lbry && tox

idea:
	mkdir -p .idea
	cp -r lbry/scripts/idea/* .idea
