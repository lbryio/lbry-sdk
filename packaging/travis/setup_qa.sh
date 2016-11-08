#!/bin/sh

SHA = echo ${TRAVIS_COMMIT} | cut -c1-10
sed -i "s/__version__ = \".*\"/__version__ = \"${SHA}\"/g" lbrynet/__init__.py

wget https://s3.amazonaws.com/lbry-ui/development/dist.zip
unzip dist.zip -d lbrynet/resources/ui
wget https://s3.amazonaws.com/lbry-ui/development/data.json -O lbrynet/resources/ui/data.json
