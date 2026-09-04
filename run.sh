#!/usr/bin/env bash
# One-command launcher for macOS and Linux.
#
# Creates a virtual environment beside this script on first run, installs the
# package into it, and starts the dashboard. Safe to re-run: an existing
# environment is reused, so the slow path happens once.
set -euo pipefail

cd "$(dirname "$0")"
VENV=".venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required but was not found on PATH."
  echo "Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "Creating a virtual environment in $VENV ..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "Installing the analyzer and its dashboard ..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[dashboard]"

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Created .env from the template. Add your LLM key before running an analysis:"
  echo "    ado-defect-analysis secrets set GROQ_API_KEY"
  echo
fi

echo "Starting the dashboard on http://localhost:8501 ..."
exec ado-defect-analysis dashboard "$@"
