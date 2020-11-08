#!/usr/bin/env bash

TARGET_HOST=$1

docker build -f lbry/scripts/Dockerfile.wallet_server -t lbry/wallet-server:segwit-dev .
IMAGE=`docker image inspect lbry/wallet-server:segwit-dev | sed -n "s/^.*Id\":\s*\"sha256:\s*\(\S*\)\".*$/\1/p"`
ssh $TARGET_HOST docker image rm lbry/wallet-server:segwit-dev
docker save $IMAGE | ssh $TARGET_HOST docker load
ssh $TARGET_HOST docker tag $IMAGE lbry/wallet-server:segwit-dev
