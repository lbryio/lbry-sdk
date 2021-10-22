#!/bin/bash

# entrypoint for wallet server Docker image

set -euo pipefail

SNAPSHOT_URL="${SNAPSHOT_URL:-}" #off by default. latest snapshot at https://lbry.com/snapshot/wallet

if [[ -n "$SNAPSHOT_URL" ]] && [[ ! -f /database/lbry-leveldb ]]; then
  files="$(ls)"
  echo "Downloading wallet snapshot from $SNAPSHOT_URL"
  wget --no-verbose --trust-server-names --content-disposition "$SNAPSHOT_URL"
  echo "Extracting snapshot..."
  filename="$(grep -vf <(echo "$files") <(ls))" # finds the file that was not there before
  case "$filename" in
    *.tgz|*.tar.gz|*.tar.bz2 )  tar xvf "$filename" --directory /database ;;
    *.zip ) unzip "$filename" -d /database ;;
    * ) echo "Don't know how to extract ${filename}. SNAPSHOT COULD NOT BE LOADED" && exit 1 ;;
  esac
  rm "$filename"
fi

/home/lbry/.local/bin/lbry-hub-elastic-sync
echo 'starting server'
/home/lbry/.local/bin/lbry-hub "$@"
