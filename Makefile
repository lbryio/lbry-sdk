.PHONY: tools lint test idea

lint:
	pylint --rcfile=setup.cfg lbry
	#mypy --ignore-missing-imports lbry

test:
	tox

idea:
	mkdir -p .idea
	cp -r scripts/idea/* .idea

start:
	dropdb lbry
	createdb lbry
	lbrynet start --full-node \
		--db-url=postgresql:///lbry --processes=2 --console=advanced --no-spv-address-filters \
		--lbrycrd-dir=${HOME}/.lbrycrd --data-dir=/tmp/tmp-lbrynet
