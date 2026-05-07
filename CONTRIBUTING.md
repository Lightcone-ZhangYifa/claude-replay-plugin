# Contributing

Thanks for your interest! `claude-replay` is small and focused — please keep PRs that way too.

## Running tests

```bash
python3 -m pytest tests/ -v
```

The test suite uses temp directories and a fake "session JSONL" — no real Claude data is needed.

## Running the engine locally

```bash
python3 scripts/replay_engine.py status --repo /path/to/your/repo
python3 scripts/replay_engine.py plan --repo /path/to/your/repo --strategy doc-files
python3 scripts/replay_engine.py execute --repo /path/to/your/repo
```

## Style

- Python 3.10+, standard library only (no dependencies).
- Type hints on public functions.
- Keep CLI flags backward-compatible — users script around them.
- New boundary strategies are welcome; add a `boundaries_<name>(...)` function and wire into `_build_boundaries`.

## Reporting bugs

Please include:
- `python3 scripts/replay_engine.py status --repo .` output
- A description of what the proposed chain looked like vs what you expected
- If safe to share, a redacted snippet of the relevant `~/.claude/projects/-*/foo.jsonl`

## Releases

Tag `vX.Y.Z`, write a brief changelog, push tag. The marketplace picks up the new `version` from `.claude-plugin/plugin.json`.
