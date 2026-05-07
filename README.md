<div align="center">

# claude-replay

### **The undo button you forgot to ask for.**

**You forgot to commit.** Claude Code wrote 165 files across a week of sessions. Your `git status` is a wall of red. You don't remember the order, you can't tell "the v2 fix you regret" from "the v1 you want to keep", and writing 20 commits by hand from a snapshot is a forensic nightmare.

**claude-replay reads Claude's own raw session JSONLs and rebuilds the commit history you forgot to make** — byte-for-byte, in order, including every intermediate change Claude made and later overwrote.

[![CI](https://github.com/Lightcone-ZhangYifa/claude-replay-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/Lightcone-ZhangYifa/claude-replay-plugin/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin: Claude Code](https://img.shields.io/badge/Plugin-Claude%20Code-blue)](https://docs.claude.com/en/docs/claude-code/plugins)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Dependencies: stdlib only](https://img.shields.io/badge/Dependencies-stdlib%20only-brightgreen)](#install)

</div>

---

## Two reasons this exists

### 🚑 1. Rescue mode: you forgot to commit

You weren't sloppy — you were in flow. Claude was building a feature, then iterating, then a sub-agent took a detour, then you context-compacted, then you opened a new session, then another, then suddenly it's been a week and you have:

```
$ git status -s | wc -l
165
```

That's the canonical "I forgot to commit" disaster. Hand-writing 20 semantic commits from a final snapshot means **inventing** history — guessing what changed when, in what order, and by which feature. You'll lose the intermediate states. You'll bundle unrelated work. You'll never recover the v1 that v2 overwrote.

You don't have to. **Claude already wrote it down.**

Every assistant turn — every `Edit`, every `Write`, every `Bash` command — was streamed to disk by Claude Code:

```
~/.claude/projects/-{your-cwd}/*.jsonl
~/.claude/projects/-{your-cwd}/subagents/*.jsonl
```

`Write` records the absolute file content. `Edit` records `(old_string, new_string)`. `Bash` records the literal command. **claude-replay reads these JSONLs at the principle level** — as a deterministic event stream — and replays them in timestamp order against the right baseline commit. The result is your real history, not a re-summarization. Including every intermediate version of a file that was later modified again. Nothing fabricated, nothing lost.

```
$ /replay
↳ status:   1274 ops across 6 sessions
↳ plan:     20 commit boundaries from docs/*.md timestamps
↳ execute:  built sandbox in 23s, byte-equal to working tree (0 diff)
↳ apply:    real repo HEAD now: 1205576 (previous tagged as backup)
```

After: a clean `git log --oneline`. You can `git revert` one feature, `git bisect` to find what broke, or push 20 PRs. Your forgotten week became 20 reviewable commits.

### 🔬 2. Research mode: you study AI agent behavior

If you research LLM agents — error recovery, tool-use patterns, multi-step planning, self-correction loops, sub-agent delegation, context management — Claude Code's session JSONLs are an extraordinary corpus, and **claude-replay gives you a structured front-end into it**.

```bash
# Export every tool call as JSON (no replay, no git side effects)
claude-replay analyze --repo /path/to/agent-experiment --format json > events.json

# Schema (one record per tool_use):
# {
#   "ts": "2026-05-06T15:11:11Z",
#   "session_id": "ff42acb7-...",
#   "is_subagent": false,
#   "tool": "Edit",
#   "file_path": "/abs/path/foo.py",
#   "input": {...},               # original tool input verbatim
#   "success": true,
#   "result_preview": "..."        # truncated tool result
# }
```

The `analyze` command also surfaces:

- **Edit retry patterns** — how often does the agent re-issue an Edit after `old_string not found`?
- **File hot-spots** — which files are touched most? In what order?
- **Sub-agent invocations** — when does the parent delegate, and to which subagent type?
- **Time gaps** — pauses between ops correlate with user-think time vs LLM latency
- **User intervention shape** — message lengths, approval cadence, correction rate

If you're studying AI agent behavior, the JSONLs are your raw data and `claude-replay analyze` is your tap.

---

## How it works (principle level)

```
┌──────────────────────────────────────┐         ┌──────────────────────────┐
│  ~/.claude/projects/-{cwd}/          │         │  /tmp/claude-replay-*/   │
│    *.jsonl  ─── main session         │  read   │  (sandbox clone of       │
│    subagents/*.jsonl                 │  ─────► │   your repo @ baseline   │
│                                      │         │   commit)                │
│  Each line = one assistant or user   │         │                          │
│  message; tool_use blocks contain    │         │  apply ops in ts order:  │
│  exact tool inputs.                  │         │    Write → set bytes     │
└──────────────────────────────────────┘         │    Edit  → str.replace   │
                                                  │    MultiEdit → seq.     │
                                                  │    Bash  → bash -c      │
                                                  │           (cwd=sandbox) │
                                                  └──────────┬───────────────┘
                                                             │
                                                             ▼
                                                  ┌──────────────────────────┐
                                                  │  diff -r sandbox repo    │
                                                  │  must be byte-equal      │
                                                  │      (== 0 entries)      │
                                                  └──────────┬───────────────┘
                                                             │ approve
                                                             ▼
                                                  ┌──────────────────────────┐
                                                  │  git fetch sandbox       │
                                                  │  git reset --hard        │
                                                  │  (real repo gets the     │
                                                  │   commit chain;          │
                                                  │   previous HEAD tagged)  │
                                                  └──────────────────────────┘
```

The mechanism is **principle-level**, not heuristic. Each op was originally applied to a deterministic state; replaying the same op against the same starting state produces the same bytes. We don't infer or summarize — we re-execute the same instructions. **Intermediate states that were later overwritten are preserved as their own commits**, because each commit boundary snapshots the state at that point in the timeline, not the final state.

---

## Install

### As a Claude Code plugin (recommended)

```
/plugin marketplace add Lightcone-ZhangYifa/claude-replay-plugin
/plugin install claude-replay@claude-replay-plugin
```

Then use `/replay`, `/replay-status`, `/replay-plan`, `/replay-execute` from any Claude Code session.

### As a standalone CLI

```bash
git clone https://github.com/Lightcone-ZhangYifa/claude-replay-plugin
alias claude-replay='python3 /path/to/claude-replay-plugin/scripts/replay_engine.py'

claude-replay status                # what's in your session JSONLs
claude-replay plan                  # preview the proposed commit chain
claude-replay execute               # build in sandbox, verify byte-equal
claude-replay execute --apply       # also rewrite real repo HEAD
claude-replay analyze --format json # structured event export (researcher mode)
```

**Requirements**: Python 3.10+, `git`, `bash`. **No external Python packages.** Linux + macOS supported (Windows via WSL).

---

## Quick start: rescue your repo in 3 commands

```bash
# 1. See what claude-replay can recover
$ claude-replay status
Project: /home/me/myrepo
Session JSONLs: 103 (6 main + 97 subagent)
File ops in scope: 1274 (Write: 312, Edit: 731, MultiEdit: 9, Bash: 222)

# 2. Preview the commit chain (uses your docs/*.md as natural boundaries)
$ claude-replay plan
Boundaries: 20

  1. [  94 ops, 33 files]  chore(replay): ssh-architecture-audit
  2. [  18 ops,  7 files]  chore(replay): volume-keys-configurable
  ...
 20. [  37 ops,  7 files]  chore(replay): fab-bubble-fix

# 3. Build it (sandbox first; byte-equality check vs working tree)
$ claude-replay execute --apply
Sandbox: /tmp/claude-replay-abc123
Commits: 20  ·  Diff vs working tree: 0 entries
Real repo HEAD now: 1205576a8d12 (previous tagged claude-replay-backup-1730912345)
```

---

## Boundary strategies

| Strategy        | When to use                                           | CLI flag                          |
|-----------------|-------------------------------------------------------|-----------------------------------|
| `doc-files`     | Each new `docs/<feature>.md` = one commit (default)  | `--boundary-glob "docs/*.md"`    |
| `time-gap`      | Sessions without docs                                 | `--gap-minutes 30`                |
| `user-approve`  | "Approve" in user messages = boundary                 | `--approve-regex "approve\|lgtm"` |
| `one-shot`      | Bare-minimum recovery — one big commit                | —                                 |
| `manual`        | Full control via JSON list of timestamps              | `--boundaries-file plan.json`     |

Mix and match: `--after 2026-05-04T15:19:00` and `--before 2026-05-06T12:00:00` to scope to a specific window.

---

## Safety

Three guarantees:

1. **The real repo is untouched until you pass `--apply`.** All replay happens in `/tmp/claude-replay-*`.
2. **`--apply` aborts if the rebuilt chain isn't byte-equal to your working tree** (overrideable with `--allow-drift` for incremental cleanup).
3. **Your previous HEAD is always tagged** as `claude-replay-backup-<unix-ts>` before any history rewrite. Roll back with `git reset --hard claude-replay-backup-<ts>`.

The sandbox runs with `core.hooksPath=/dev/null` so a slow or failing pre-commit hook can't corrupt the chain mid-replay.

---

## Real-world numbers

This plugin was built to solve exactly this problem in a 165-file working tree spanning **6 Claude Code sessions over 3 days**, including 19 sub-agent invocations.

| Metric | Value |
|---|---|
| Session JSONLs ingested | 103 |
| Total tool calls extracted | 12,264 |
| File-modifying ops replayed | 1,274 |
| Commits produced | 21 |
| Final byte-divergence vs working tree | **0** files |
| End-to-end runtime | **23 seconds** |

Result: a clean, reviewable history. The user could `git revert` a single regretted commit while keeping its v1 predecessor intact.

---

## For researchers: structured event export

`claude-replay analyze` emits a normalized event log of every tool use Claude made, suitable for downstream analysis. Two formats:

```bash
claude-replay analyze --format json     # one JSON record per line (JSONL)
claude-replay analyze --format csv      # flat CSV with sensible columns
```

Records carry timestamps, session IDs (so sub-agent ops are linkable to their parent), tool names, full inputs, success flags, and truncated result previews. Headers / metadata go to stderr; the data stream goes to stdout, so you can pipe directly into `jq`, `pandas`, `duckdb`:

```bash
# Fail rate per tool
claude-replay analyze --format json \
  | jq -r '[.tool, .success] | @csv' \
  | sort | uniq -c | sort -rn

# Edit retry pattern: same file edited within 60s after a failed Edit
claude-replay analyze --format csv | python3 retry_analyzer.py

# Sub-agent delegation graph
claude-replay analyze --format json --include-tool Task | jq '.input.subagent_type'
```

See [`docs/researchers.md`](docs/researchers.md) for the full event schema and example analyses.

---

## What it does NOT do

- **Does not invent commits Claude didn't make.** The chain is a faithful replay of recorded ops, not a re-summarization of the diff.
- **Does not modify your session JSONLs.** Read-only on Claude's side.
- **Does not run your pre-commit hooks during sandbox replay.** A hook failure mid-replay can't corrupt the chain. Hooks run again normally on later real-repo commits.
- **Does not push to any remote.** You explicitly do that after reviewing.
- **Does not work without git.** The repo must be a git repo with at least one commit (the baseline).

---

## FAQ

### Does this work for sub-agents?
Yes. JSONLs from `subagents/*.jsonl` are merged into the same chronological timeline (since v0.1.0).

### What if a `sed -i` command in the original session was complex?
Most patterns replay perfectly. For exotic escapes that don't, the verification diff catches it and you can either add a final `chore: align with working tree` commit or pass `--allow-drift` to apply anyway and patch up.

### What if the user manually edited files outside Claude?
Those edits won't appear in any JSONL, so they show up as a sandbox-vs-working-tree divergence. Pin them into a final alignment commit.

### What if I ran claude-replay itself in the session I want to replay?
Use `--before <ts>` to cap the replay before your own forensic work began. (Self-replay would otherwise try to re-run claude-replay's own bash scripts inside the sandbox.)

### Can I undo a `--apply`?
Yes: `git reset --hard claude-replay-backup-<unix-ts>` (the tag is created automatically before every history rewrite).

### Why not just use `git reflog`?
`git reflog` only knows about operations on the .git store (commits, branches, resets). Your forgotten work was never committed in the first place — there's nothing in the reflog to recover. The JSONLs are the only source of truth.

### Does this work with project-types other than Android / Kotlin?
Yes. The engine is language-agnostic. It just replays bytes; it doesn't parse what's in the files.

### What about Windows?
Use WSL. The engine relies on `bash` to faithfully re-run captured Bash ops; native Windows shells have different semantics.

---

## Contributing

PRs welcome. Please run `python3 -m pytest tests/ -v` first. New boundary strategies, better Bash heuristics, additional export formats — all wanted. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Star history

If this rescued you, ⭐ helps others find it.

## License

MIT — use it, fork it, ship it.
