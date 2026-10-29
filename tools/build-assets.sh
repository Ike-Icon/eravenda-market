#!/usr/bin/env bash
# Rebuilds the Tailwind stylesheet and the minified scripts. Run it after you
# change any Tailwind class, custom.css or a script, then commit the results.
set -euo pipefail
exec python3 "$(dirname "$0")/build_assets.py"
