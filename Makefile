.PHONY: install tools lint test test-unit test-unit-coverage test-integration idea

install:
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
