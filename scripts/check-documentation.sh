#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} == --staged && $# == 1 ]]; then
  changed=$(git diff --cached --name-only --diff-filter=ACMR)
elif [[ $# == 1 ]]; then
  changed=$(git diff --name-only --diff-filter=ACMR "$1")
else
  echo "Usage: $0 --staged | <git-revision-range>" >&2
  exit 2
fi

code_changed=0
docs_changed=0
while IFS= read -r path; do
  case $path in
    backend/*|web/*|scripts/*.py|pyproject.toml|requirements*.txt|Dockerfile) code_changed=1 ;;
  esac
  case $path in
    README.md|docs/*.md) docs_changed=1 ;;
  esac
done <<< "$changed"

if (( code_changed && ! docs_changed )); then
  echo "Application changes require a Markdown update in README.md or docs/." >&2
  exit 1
fi
