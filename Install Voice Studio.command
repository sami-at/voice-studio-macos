#!/bin/zsh
set -e
cd -- "${0:A:h}"
VOICE_STUDIO_PYTHON="$(command -v python3.11 || true)"
if [[ -z "$VOICE_STUDIO_PYTHON" && -x /opt/homebrew/bin/python3.11 ]]; then
  VOICE_STUDIO_PYTHON=/opt/homebrew/bin/python3.11
fi
if [[ -z "$VOICE_STUDIO_PYTHON" ]]; then
  print 'Python 3.11 is required. Install it with Homebrew: brew install python@3.11'
  read '?Press Return to close.'
  exit 1
fi
if [[ -d .venv ]]; then
  "$VOICE_STUDIO_PYTHON" -m venv --upgrade .venv
else
  "$VOICE_STUDIO_PYTHON" -m venv .venv
fi
if [[ -f .setup-wheels/.complete ]]; then
  .venv/bin/python -m pip install --no-index --find-links .setup-wheels -r requirements.lock.txt
else
  .venv/bin/python -m pip install --cache-dir .setup-cache -r requirements.lock.txt
fi
.venv/bin/python scripts/download_models.py
mkdir -p local_data/logs
.venv/bin/python scripts/build_app.py
open 'Voice Studio.app'
