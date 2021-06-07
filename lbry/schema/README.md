Schema
=====

Those files are generated from the [types repo](https://github.com/lbryio/types). If you are modifying/adding a new type, make sure it is cloned in the same root folder as the SDK repo, like:

```
repos/
    - lbry-sdk/
    - types/
```

Then, [download protoc 3.2.0](https://github.com/protocolbuffers/protobuf/releases/tag/v3.2.0), add it to your PATH. On linux it is:

```bash
cd ~/.local/bin
wget https://github.com/protocolbuffers/protobuf/releases/download/v3.2.0/protoc-3.2.0-linux-x86_64.zip
unzip protoc-3.2.0-linux-x86_64.zip bin/protoc -d..
```

Finally, `make` should update everything in place.


### Why protoc 3.2.0?
Different/newer versions will generate larger diffs and we need to make sure they are good. In theory, we can just update to latest and it will all work, but it is a good practice to check blockchain data and retro compatibility before bumping versions (if you do, please update this section!).
