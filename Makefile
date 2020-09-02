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
	dropdb lbry --if-exists
	createdb lbry
	lbrynet start --full-node \
		--db-url=postgresql:///lbry --workers=0 --console=advanced --no-spv-address-filters \
		--lbrycrd-rpc-user=lbry --lbrycrd-rpc-pass=somethingelse \
		--lbrycrd-dir=${HOME}/.lbrycrd --data-dir=/tmp/tmp-lbrynet
