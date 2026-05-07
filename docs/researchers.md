# For researchers: AI agent behavior analysis

Claude Code's session JSONLs are a rich corpus for studying LLM agent behavior in real, unrestricted conditions: long-horizon tasks, sub-agent delegation, error recovery, tool retry patterns, user-in-the-loop correction. `claude-replay analyze` is a structured tap into this data.

## Why this matters

Most agent benchmarks are short, scripted, and synthetic. Claude Code session JSONLs capture **months of real human-agent collaboration** on real codebases — including the messy parts: failed edits, sub-agent escalations, context compactions, mid-task pivots, multi-day workflows.

If you're researching:

- **Tool retry / error recovery**: how often does the agent re-issue an Edit after `old_string not found`? Does the retry rate correlate with file size or LLM context length?
- **Sub-agent delegation**: when does the parent delegate vs do work itself? What sub-agent types are most common?
- **Self-correction loops**: how many turns does the agent take to fix a regression it introduced?
- **Tool-use patterns**: which tools are called sequentially vs in parallel?
- **Context management**: how do operations distribute across the session lifetime? Where do compactions happen?

…the JSONLs are your raw data and `claude-replay analyze` is your front-end.

## Event schema

`claude-replay analyze --format json` emits one JSONL record per tool use:

```json
{
  "ts": "2026-05-06T15:11:11.123Z",
  "session_id": "ff42acb7-44ab-487c-b83e-594b041a4a96",
  "is_subagent": false,
  "tool": "Edit",
  "tool_use_id": "toolu_01abc...",
  "file_path": "/abs/path/foo.py",
  "input": {
    "file_path": "/abs/path/foo.py",
    "old_string": "def f(): return 1",
    "new_string": "def f(): return 2",
    "replace_all": false
  },
  "success": true,
  "result_preview": "The file /abs/path/foo.py has been updated successfully."
}
```

Field reference:

| Field             | Type    | Notes                                                                     |
|-------------------|---------|---------------------------------------------------------------------------|
| `ts`              | string  | ISO 8601 timestamp, ms precision when available                          |
| `session_id`      | string  | UUID of the session JSONL file (sub-agents have their own UUIDs)         |
| `is_subagent`     | bool    | true if from `subagents/*.jsonl`                                          |
| `tool`            | string  | tool name: `Edit`, `Write`, `Bash`, `Task`, `Read`, `Grep`, ...           |
| `tool_use_id`     | string  | unique per tool invocation, used to join with results                     |
| `file_path`       | string? | for file-touching tools; null for Bash/Grep/etc.                          |
| `input`           | object  | original tool input verbatim (truncated unless `--full-input`)            |
| `success`         | bool    | `false` if the tool result was `is_error: true`                           |
| `result_preview`  | string  | first 300 chars of the tool result (truncated, newlines preserved)        |

## Quick analyses

### Retry pattern: same Edit issued twice within 60s after a failure

```python
import json, subprocess
from collections import defaultdict
from datetime import datetime

events = [json.loads(l) for l in subprocess.check_output(
    ["claude-replay", "analyze", "--format", "json"], text=True
).splitlines()]

retries = defaultdict(int)
prev_fail: dict[str, str] = {}  # file_path → ts of failed Edit
for e in events:
    if e["tool"] != "Edit" or not e.get("file_path"):
        continue
    fp = e["file_path"]
    if not e["success"]:
        prev_fail[fp] = e["ts"]
        continue
    if fp in prev_fail:
        gap = (datetime.fromisoformat(e["ts"].rstrip("Z"))
               - datetime.fromisoformat(prev_fail[fp].rstrip("Z"))).total_seconds()
        if gap < 60:
            retries[fp] += 1
        del prev_fail[fp]

print(f"Files with successful retry within 60s after Edit failure: {len(retries)}")
for fp, n in sorted(retries.items(), key=lambda x: -x[1])[:10]:
    print(f"  {n:3d}x  {fp}")
```

### Sub-agent invocation graph

```bash
claude-replay analyze --format json --include-tool Task \
  | jq -r '[.session_id, .input.subagent_type, .input.description] | @csv'
```

### Per-tool failure rate

```bash
claude-replay analyze --format stats
# Output:
# By tool:
#    731  Edit                success=696 ( 95.2%)
#    312  Write               success=312 (100.0%)
#   1563  Bash                success=1532 ( 98.0%)
#    ...
```

### Session-length distribution

```bash
claude-replay analyze --format csv \
  | python3 -c "
import sys, csv
from collections import defaultdict
counts = defaultdict(int)
for row in csv.DictReader(sys.stdin):
    counts[row['session_id']] += 1
for sid, n in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'{n:6d}  {sid}')
"
```

### Time gaps (correlate with user-think vs LLM-latency)

```bash
claude-replay analyze --format json | python3 -c "
import json, sys
from datetime import datetime
prev = None
for line in sys.stdin:
    e = json.loads(line)
    cur = datetime.fromisoformat(e['ts'].rstrip('Z'))
    if prev:
        gap = (cur - prev).total_seconds()
        if gap > 5:
            print(f'{gap:7.1f}s  {e[\"tool\"]}  {e.get(\"file_path\",\"\")}')
    prev = cur
" | sort -rn | head -20
```

## Reproducibility

Two analyses on the same session JSONL produce identical events. The data is append-only; timestamps are stable. You can pin to a specific window with `--after` / `--before` for paper-friendly subset definitions.

## Ethics & privacy

The session JSONLs contain everything Claude saw and did, including:

- File contents the agent read (potentially proprietary)
- User messages (potentially private)
- Tool results (potentially containing secrets that the agent unintentionally surfaced)

If you publish derived data:

- **Strip absolute paths** that may identify users (replace `/home/<user>/...` with `<repo-root>/...`)
- **Drop `input.content` and `input.old_string`/`input.new_string`** unless your study requires file content
- **Aggregate session IDs** to user IDs only with consent
- **Redact `result_preview`** if it may leak credentials

`claude-replay analyze` does not strip these by default — you control what to keep when piping downstream.

## Citing this tool

```
@software{claude_replay,
  author = {Lightcone-ZhangYifa},
  title  = {claude-replay: byte-perfect reconstruction of git commits from Claude Code session history},
  year   = {2026},
  url    = {https://github.com/Lightcone-ZhangYifa/claude-replay-plugin},
  version = {0.1.0}
}
```
