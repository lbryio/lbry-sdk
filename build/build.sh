#!/bin/bash

set -euo pipefail
set -x

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$ROOT"
BUILD_DIR="$ROOT/build"

FULL_BUILD="${FULL_BUILD:-false}"
if [ -n "${TEAMCITY_VERSION:-}" -o -n "${APPVEYOR:-}" ]; then
  FULL_BUILD="true"
fi

[ -d "$BUILD_DIR/bulid" ] && rm -rf "$BUILD_DIR/build"
[ -d "$BUILD_DIR/dist" ] && rm -rf "$BUILD_DIR/dist"

if [ "$FULL_BUILD" == "true" ]; then
  # install dependencies
  $BUILD_DIR/prebuild.sh

  VENV="$BUILD_DIR/venv"
  if [ -d "$VENV" ]; then
    rm -rf "$VENV"
  fi
  virtualenv "$VENV"
  set +u
  source "$VENV/bin/activate"
  set -u

  # must set build before installing lbrynet. otherwise it has no effect
  python "$BUILD_DIR/set_build.py"
fi

cp "$ROOT/requirements.txt" "$BUILD_DIR/requirements_base.txt"
(
  cd "$BUILD_DIR"
  pip install Cython==0.27.3
  pip install -r requirements.txt
)

(
  cd "$BUILD_DIR"
  pyinstaller -y daemon.onefile.spec
  pyinstaller -y cli.onefile.spec
  pyinstaller -y console.onefile.spec
)

python "$BUILD_DIR/zip_daemon.py"

if [ "$FULL_BUILD" == "true" ]; then
  # electron-build has a publish feature, but I had a hard time getting
  # it to reliably work and it also seemed difficult to configure. Not proud of
  # this, but it seemed better to write my own.
  python "$BUILD_DIR/upload_assets.py"

  deactivate
fi

echo 'Build complete.'
