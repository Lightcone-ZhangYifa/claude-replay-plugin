---
description: Export structured event log of every Claude tool call (for AI-agent behavior research)
allowed-tools: Bash
argument-hint: "[--format json|csv|stats] [--include-tool Edit] [--full-input]"
---

Run the analyze subcommand to emit a normalized event log.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" analyze --repo . $ARGUMENTS
```

Default format is JSON-Lines (one record per line on stdout, metadata on stderr) — pipe-friendly for `jq`, `pandas`, `duckdb`. Use `--format stats` for a human-readable summary, `--format csv` for spreadsheet/dataframe ingest.

Useful one-liners to suggest to the user after running:

```bash
# Failure rate per tool
... analyze --format stats

# Retry pattern
... analyze --format json | jq 'select(.tool=="Edit" and .success==false) | .file_path' | sort | uniq -c | sort -rn

# Sub-agent invocations
... analyze --format json --include-tool Task | jq '.input.subagent_type'
```

See `docs/researchers.md` for the full event schema.
