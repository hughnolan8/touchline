#!/usr/bin/env sh
set -eu

git config core.hooksPath .githooks
echo "Touchline Git hooks enabled."
