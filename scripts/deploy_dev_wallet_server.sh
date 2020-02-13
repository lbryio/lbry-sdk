#!/usr/bin/env bash

# usage: update_dev_wallet_server.sh <host to update>
TARGET_HOST=$1

SCRIPTS_DIR=`dirname $0`
LBRY_DIR=`dirname $SCRIPTS_DIR`

# build the image
docker build -f $LBRY_DIR/docker/Dockerfile.wallet_server -t lbry/wallet-server:development $LBRY_DIR
IMAGE=`docker image inspect lbry/wallet-server:development | sed -n "s/^.*Id\":\s*\"sha256:\s*\(\S*\)\".*$/\1/p"`

# push the image to the server
ssh $TARGET_HOST docker image prune --force
docker save $IMAGE | ssh $TARGET_HOST docker load
ssh $TARGET_HOST docker tag $IMAGE lbry/wallet-server:development

# restart the wallet server
ssh $TARGET_HOST docker-compose down
ssh $TARGET_HOST WALLET_SERVER_TAG="development" docker-compose up -d
