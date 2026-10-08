#!/usr/bin/env bash
# One-command start: ./run.sh   (env: PORT=8000 HOST=0.0.0.0 PRICE_SOURCE=auto|yahoo|sim)
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
# Local demo: show the password-reset link in the API response when SMTP is not configured.
# Set DEV_SHOW_RESET_LINK=0 before ./run.sh to turn that off.
: "${DEV_SHOW_RESET_LINK:=1}"
export DEV_SHOW_RESET_LINK
exec .venv/bin/uvicorn --factory app.main:create_app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
