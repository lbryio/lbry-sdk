#!/bin/bash

# entrypoint for wallet server Docker image

SNAPSHOT_URL="${SNAPSHOT_URL:-}" #off by default. latest snapshot at https://lbry.com/snapshot/wallet

if [[ -n "$SNAPSHOT_URL" ]] && [[ ! -f /database/claims.db ]]; then
  echo "Downloading wallet snapshot from $SNAPSHOT_URL"
  wget -O wallet_snapshot.tar.bz2 "$SNAPSHOT_URL"
  echo "Extracting snapshot..."
  tar xvjf wallet_snapshot.tar.bz2 --directory /database
  rm wallet_snapshot.tar.bz2
fi

/home/lbry/.local/bin/torba-server "$@"
