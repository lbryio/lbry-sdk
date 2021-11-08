#!/bin/bash

SNAPSHOT_HEIGHT="1072108"

HUB_VOLUME_PATH="/var/lib/docker/volumes/${USER}_wallet_server"
ES_VOLUME_PATH="/var/lib/docker/volumes/${USER}_es01"

SNAPSHOT_TAR_NAME="wallet_server_snapshot_${SNAPSHOT_HEIGHT}.tar.gz"
ES_SNAPSHOT_TAR_NAME="es_snapshot_${SNAPSHOT_HEIGHT}.tar.gz"

SNAPSHOT_URL="https://snapshots.lbry.com/hub/${SNAPSHOT_TAR_NAME}"
ES_SNAPSHOT_URL="https://snapshots.lbry.com/hub/${ES_SNAPSHOT_TAR_NAME}"

echo "fetching wallet server snapshot"
wget $SNAPSHOT_URL
echo "decompressing wallet server snapshot"
tar -xf $SNAPSHOT_TAR_NAME
sudo mkdir -p $HUB_VOLUME_PATH
sudo rm -rf "${HUB_VOLUME_PATH}/_data"
sudo chown -R 999:999 "snapshot_${SNAPSHOT_HEIGHT}"
sudo mv "snapshot_${SNAPSHOT_HEIGHT}" "${HUB_VOLUME_PATH}/_data"
echo "finished setting up wallet server snapshot"

echo "fetching elasticsearch snapshot"
wget $ES_SNAPSHOT_URL
echo "decompressing elasticsearch snapshot"
tar -xf $ES_SNAPSHOT_TAR_NAME
sudo chown -R $USER:root "snapshot_es_${SNAPSHOT_HEIGHT}"
sudo chmod -R 775 "snapshot_es_${SNAPSHOT_HEIGHT}"
sudo mkdir -p $ES_VOLUME_PATH
sudo rm -rf "${ES_VOLUME_PATH}/_data"
sudo mv "snapshot_es_${SNAPSHOT_HEIGHT}" "${ES_VOLUME_PATH}/_data"
echo "finished setting up elasticsearch snapshot"
