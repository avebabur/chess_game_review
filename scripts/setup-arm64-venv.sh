#!/bin/bash
# Recreate the project venv with native Apple Silicon (arm64) Python.
# Use this if macOS warns that Python includes Intel-only components.

set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"

if [ "$(uname -m)" != "arm64" ]; then
  echo "This Mac is not Apple Silicon. Use: python3 -m venv venv"
  exit 1
fi

pick_arm64_python() {
  local candidate arch
  for candidate in \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /usr/local/bin/python3 \
    /usr/bin/python3
  do
    [ -x "$candidate" ] || continue
    arch="$(arch -arm64 "$candidate" -c 'import platform; print(platform.machine())' 2>/dev/null || true)"
    if [ "$arch" = "arm64" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON="$(pick_arm64_python || true)"
if [ -z "$PYTHON" ]; then
  echo "No arm64 Python found."
  echo "Install one, then rerun this script:"
  echo "  brew install python@3.12"
  echo "  # or download the Apple Silicon installer from https://www.python.org/downloads/macos/"
  exit 1
fi

echo "Using arm64 Python: $PYTHON"
"$PYTHON" --version
file "$PYTHON"

if [ -d venv ]; then
  echo "Removing old venv…"
  rm -rf venv
fi

echo "Creating arm64 venv…"
arch -arm64 "$PYTHON" -m venv venv

source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Verifying venv architecture…"
VENV_ARCH="$(arch -arm64 venv/bin/python3 -c 'import platform; print(platform.machine())')"
if [ "$VENV_ARCH" != "arm64" ]; then
  echo "Error: venv is still $VENV_ARCH (expected arm64)."
  exit 1
fi

echo "Done. Rebuild the app:"
echo "  ./scripts/build-macos-app.sh"
echo "  cp -R \"dist/Chess Review.app\" /Applications/"
