#!/usr/bin/env bash
# Keeps the repository settings in .github/repo-settings.json, in the format of
# GitHub's `PATCH /repos/{owner}/{repo}` endpoint (auto merge, branch cleanup,
# secret scanning, ...). Settings not in the file are left alone.
#
#   scripts/repo-settings.sh diff    # show how GitHub differs from the file
#   scripts/repo-settings.sh apply   # send the file to GitHub
#
# Needs gh, logged in as a repository admin, and jq.
set -euo pipefail

REPO="${REPO:-TheRealArthurDent/private-cloud}"
FILE="$(git rev-parse --show-toplevel)/.github/repo-settings.json"

# The live values of exactly the fields the file sets, nested ones included.
live_settings() {
  gh api "repos/$REPO" | jq --sort-keys --slurpfile want "$FILE" '
    . as $live
    | [$want[0] | paths(scalars)] as $paths
    | reduce $paths[] as $p ({}; setpath($p; $live | getpath($p)))'
}

cmd_diff() {
  diff -u --label "github/$REPO" --label "file/repo-settings.json" \
    <(live_settings) <(jq --sort-keys . "$FILE")
}

cmd_apply() {
  gh api --method PATCH "repos/$REPO" --input "$FILE" >/dev/null
  echo "applied $(basename "$FILE") to $REPO"
  cmd_diff && echo "GitHub matches the file"
}

case "${1:-}" in
  diff) cmd_diff ;;
  apply) cmd_apply ;;
  *)
    echo "usage: $0 diff | apply" >&2
    exit 2
    ;;
esac
