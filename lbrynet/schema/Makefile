build:
	rm proto/* -rf
	cd proto && protoc --python_out=. -I ../../../../types/proto/ ../../../../types/proto/*.proto
	sed -e 's/^import\ \(.*\)_pb2\ /from . import\ \1_pb2\ /g' -i proto/*.py
	touch proto/__init__.py

