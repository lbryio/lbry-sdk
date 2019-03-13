build:
	rm types/v1/* types/v2/* -rf
	touch types/v1/__init__.py types/v2/__init__.py
	cd types/v1/ && protoc --python_out=. -I ../../../../../types/v1/proto/ ../../../../../types/v1/proto/*.proto
	sed -e 's/^import\ \(.*\)_pb2\ /from . import\ \1_pb2\ /g' -i types/v1/*.py
	cd types/v2/ && protoc --python_out=. -I ../../../../../types/v2/proto/ ../../../../../types/v2/proto/*.proto
