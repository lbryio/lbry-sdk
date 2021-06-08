.PHONY: install tools lint test test-unit test-unit-coverage test-integration idea

install:
	pip install https://s3.amazonaws.com/files.lbry.io/python_libtorrent-1.2.4-py3-none-any.whl
	CFLAGS="-DSQLITE_MAX_VARIABLE_NUMBER=2500000" pip install -U https://github.com/rogerbinns/apsw/releases/download/3.30.1-r1/apsw-3.30.1-r1.zip \
		--global-option=fetch \
		--global-option=--version --global-option=3.30.1 --global-option=--all \
		--global-option=build --global-option=--enable --global-option=fts5
	pip install -e .

tools:
	pip install mypy==0.701 pylint==2.4.4
	pip install coverage astroid pylint

lint:
	pylint --rcfile=setup.cfg lbry
	#mypy --ignore-missing-imports lbry

test: test-unit test-integration

test-unit:
	python -m unittest discover tests.unit

test-unit-coverage:
	coverage run -p --source=lbry -m unittest discover -vv tests.unit

test-integration:
	tox

idea:
	mkdir -p .idea
	cp -r scripts/idea/* .idea

elastic-docker:
	docker run -d -v lbryhub:/usr/share/elasticsearch/data -p 9200:9200 -p 9300:9300 -e"ES_JAVA_OPTS=-Xms512m -Xmx512m" -e "discovery.type=single-node" docker.elastic.co/elasticsearch/elasticsearch:7.12.1
