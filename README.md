# claude-replay

> **Recover lost git history from Claude Code session JSONLs.**
> Byte-perfect chronological replay of every `Edit` / `Write` / `Bash` op into a clean, semantic commit chain.

[![CI](https://github.com/Lightcone-ZhangYifa/claude-replay-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/Lightcone-ZhangYifa/claude-replay-plugin/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin: Claude Code](https://img.shields.io/badge/Plugin-Claude%20Code-blue)](https://docs.claude.com/en/docs/claude-code/plugins)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![No deps](https://img.shields.io/badge/Dependencies-stdlib%20only-brightgreen)](#installation)

## The problem

You've been using Claude Code. Across many sessions you accumulated **165 uncommitted files**, fifteen new design docs, six refactors, three tries at one feature, and a deletion you wish you hadn't made. `git status` is a wall of red. You know roughly *what* you did but the *order* is gone, you can't disentangle "the swipe-actions v2 fix" from "the v1 you want to keep", and writing 20 commits by hand from a snapshot is a forensic nightmare.

## The insight

Claude Code already wrote it down. Every assistant turn — including every tool call's exact input — is persisted to JSONL files at `~/.claude/projects/-{cwd}/*.jsonl` (and `subagents/*.jsonl` for sub-agents). `Write` calls capture the absolute file content. `Edit` calls capture `(old_string, new_string)`. `Bash` calls capture the literal command. **Replay them in timestamp order against the right baseline commit and you reproduce the exact same byte sequence.**

## What this plugin does

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  ~/.claude/projects/     │         │  /tmp/claude-replay-*/   │
│   -my-project/*.jsonl    │  ──►    │  (sandbox clone @        │
│   subagents/*.jsonl      │         │    baseline commit)      │
└──────────────────────────┘         │                          │
                                     │  replay every op in ts   │
                                     │  order, commit at each   │
                                     │  boundary                │
                                     └──────────┬───────────────┘
                                                │
                                                ▼
                                     ┌──────────────────────────┐
                                     │  diff sandbox vs repo    │
                                     │  must be byte-equal      │
                                     │      (== 0 entries)      │
                                     └──────────┬───────────────┘
                                                │ approval
                                                ▼
                                     ┌──────────────────────────┐
                                     │  git fetch → reset       │
                                     │  real repo gets the      │
                                     │  20-commit chain         │
                                     └──────────────────────────┘
```

## Installation

Install via the Claude Code plugin marketplace (recommended):

```
/plugin install claude-replay
```

Or by adding this repo as a marketplace:

```
/plugin marketplace add Lightcone-ZhangYifa/claude-replay-plugin
/plugin install claude-replay@Lightcone-ZhangYifa
```

**Requires**: Python 3.10+, git, bash. **No external Python packages.** Linux + macOS supported (Windows via WSL).

## Usage

```
/replay              ← guided end-to-end (status → plan → confirm → build → verify → apply)
/replay-status       ← what's in your session JSONLs (read-only)
/replay-plan         ← preview the proposed commit chain (read-only)
/replay-execute      ← build the chain in a sandbox, verify byte-equality
/replay-execute --apply   ← also rewrite the real repo's HEAD (DESTRUCTIVE)
```

You can also drive it directly:

```bash
python3 ~/.claude/plugins/claude-replay/scripts/replay_engine.py status
python3 ~/.claude/plugins/claude-replay/scripts/replay_engine.py plan --strategy doc-files
python3 ~/.claude/plugins/claude-replay/scripts/replay_engine.py execute --apply
```

## Boundary strategies

| Strategy        | When to use                                        | Example                          |
|-----------------|----------------------------------------------------|----------------------------------|
| `doc-files`     | Each `docs/<feature>.md` = one commit (default)   | `--boundary-glob "docs/*.md"`   |
| `time-gap`      | Sessions without docs                              | `--gap-minutes 30`               |
| `user-approve`  | "Approve" in user messages = boundary              | `--approve-regex "approve\|lgtm"` |
| `one-shot`      | Bare-minimum recovery — one big commit             | —                                |
| `manual`        | Full control via JSON list                         | `--boundaries-file plan.json`    |

## Safety

- Always replays into a **temp sandbox first**; real repo is untouched until `--apply`.
- `--apply` aborts if the sandbox isn't byte-equal to the working tree (override with `--allow-drift`).
- Previous HEAD is **tagged** as `claude-replay-backup-<unix-ts>` before any rewrite.
- Sandbox uses `core.hooksPath=/dev/null` to avoid running the user's pre-commit hooks during replay.

## Real-world numbers

This plugin was built to solve exactly this problem in a 165-file working tree spanning 6 Claude Code sessions over 3 days. The replay produced **21 commits**, applied **1274 ops** (Write/Edit/MultiEdit + Bash sed/rm/mv), and matched the working tree **byte-for-byte** with **0 divergent entries**. End-to-end runtime: under 30 seconds. The result is a clean `git log --oneline` you can `git revert` from, `git bisect` against, or push to a PR.

## What it does NOT do

- It does **not** invent commits Claude didn't actually do. The chain is a faithful replay of the recorded ops, not a re-summarization.
- It does **not** modify your session JSONLs.
- It does **not** run your pre-commit hooks during sandbox replay (so a hook failure mid-replay can't corrupt the chain).
- It does **not** push to any remote. You explicitly do that after reviewing the chain.

## Common scenarios

**"I want to undo just one feature out of the chain."**
After applying: `git revert <sha-of-that-commit>`. Because the chain is granular, reverting one feature doesn't touch the others.

**"My session JSONLs include forensic work I did with claude-replay itself."**
Cap the replay before that work began: `--before "2026-05-06T15:19:00"`.

**"Some files have whitespace divergence after replay."**
Likely a `sed -i` pattern with quoting that didn't replay perfectly. Inspect with `git diff <sandbox> .`. Fix by adding a final `chore: align` commit, or use `--allow-drift` and hand-fix in a follow-up.

## Contributing

PRs welcome. Run `python3 -m pytest tests/` and `python3 scripts/replay_engine.py status` to sanity-check.

## License

MIT
