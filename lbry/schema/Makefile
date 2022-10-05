build:
	rm -rf types/v2/*
	touch types/v2/__init__.py
	cd types/v2/ && protoc --python_out=. -I ../../../../../types/v2/proto/ ../../../../../types/v2/proto/*.proto
	cd types/v2/ && cp ../../../../../types/jsonschema/* ./
	sed -e 's/^import\ \(.*\)_pb2\ /from . import\ \1_pb2\ /g' -i.bak types/v2/*.py
