# Changelog

All notable changes to claude-replay are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-07

### Added
- Initial release.
- Core replay engine (`scripts/replay_engine.py`) — zero-dependency Python 3.10+.
- Five boundary strategies: `doc-files`, `time-gap`, `user-approve`, `one-shot`, `manual`.
- Slash commands: `/replay`, `/replay-status`, `/replay-plan`, `/replay-execute`, `/replay-analyze`.
- Skill: `claude-replay`.
- `analyze` subcommand for AI-agent behavior research (JSONL/CSV/stats output).
- Sub-agent (`subagents/*.jsonl`) ingestion built in.
- Sandbox-first safety model with byte-equality verification.
- Automatic backup tag (`claude-replay-backup-<unix-ts>`) before any history rewrite.
- Tests: 5 pytest cases including end-to-end byte-equality assertion.
- CI: GitHub Actions matrix on Ubuntu/macOS × Python 3.10/3.11/3.12.
- Marketplace metadata for one-line install.

### Validated
- Reconstructed a 21-commit chain from 1274 ops across 6 sessions / 103 JSONLs in <30s, byte-equal to the original working tree.
