#!/bin/sh
# ./builder serve | export <project> [--install] | doctor
# needs Python 3.10+: a .venv next to the repositories (or in this one) wins over the system python3
cd "$(dirname "$0")" || exit 1
for py in "$ACNLB_PYTHON" ./.venv/bin/python ../.venv/bin/python python3; do
  [ -n "$py" ] && command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null && exec "$py" -m acnlb "$@"
done
echo "builder: Python 3.10 or newer is needed (set ACNLB_PYTHON, or make a .venv)" >&2
exit 1
