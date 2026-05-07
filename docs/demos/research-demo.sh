#!/usr/bin/env bash
# Pre-canned demo helper used by 04-research.tape
exec claude-replay analyze --format json 2>/dev/null \
  | jq -r 'select(.tool=="Edit" and .success==false) | .file_path' \
  | sort | uniq -c | sort -rn | head -8
