#!/bin/sh
# ./builder serve | export <project> [--install] | doctor
cd "$(dirname "$0")" && exec python3 -m acnlb "$@"
