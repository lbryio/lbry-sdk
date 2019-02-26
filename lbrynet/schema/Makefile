build:
	rm proto2/* proto3/* -rf
	cd proto2 && protoc --python_out=. -I ../../../../types/proto/v1/ ../../../../types/proto/v1/*.proto
	sed -e 's/^import\ \(.*\)_pb2\ /from . import\ \1_pb2\ /g' -i proto2/*.py
	touch proto2/__init__.py
	cd proto3 && protoc --python_out=. -I ../../../../types/proto/v2/ ../../../../types/proto/v2/*.proto
	sed -e 's/^import\ \(.*\)_pb2\ /from . import\ \1_pb2\ /g' -i proto3/*.py
	touch proto3/__init__.py

