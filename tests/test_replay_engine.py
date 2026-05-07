"""End-to-end test: build a fake session JSONL + repo, run the engine, assert byte-equal."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make the engine importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import replay_engine as re_  # noqa: E402


def _git(repo: Path, *args: str, check: bool = True, capture: bool = False):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=capture, text=True)


def _init_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("baseline\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _ts(offset_seconds: int) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _make_jsonl(session_dir: Path, name: str, records: list[dict]) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    p = session_dir / f"{name}.jsonl"
    with p.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return p


def _tool_use(tu_id: str, ts: str, name: str, inp: dict) -> dict:
    return {
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tu_id, "name": name, "input": inp}],
        },
    }


def _tool_result(tu_id: str, ts: str, is_error: bool = False) -> dict:
    return {
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tu_id,
                          "content": "ok", "is_error": is_error}],
        },
    }


def test_glob_to_regex():
    p = re_._glob_to_regex("docs/*.md")
    assert p.search("/abs/repo/docs/foo.md")
    assert p.search("docs/foo.md")
    assert not p.search("docs/sub/foo.md")
    p2 = re_._glob_to_regex("docs/**/*.md")
    assert p2.search("docs/sub/foo.md")


def test_end_to_end_doc_files_strategy():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo = _init_repo(tmp)

        # Fake the session-dir lookup by patching project_session_dir
        session_dir = tmp / "sessions"
        orig = re_.project_session_dir
        re_.project_session_dir = lambda cwd=None: session_dir

        try:
            # Build a synthetic session: 2 features, each starts with a doc Write.
            records = [
                # Feature 1
                _tool_use("u1", _ts(10), "Write", {
                    "file_path": str(repo / "docs/feature-a.md"),
                    "content": "# feature A\n",
                }),
                _tool_result("u1", _ts(11)),
                _tool_use("u2", _ts(20), "Write", {
                    "file_path": str(repo / "src/a.py"),
                    "content": "def a(): return 1\n",
                }),
                _tool_result("u2", _ts(21)),
                # Feature 2
                _tool_use("u3", _ts(30), "Write", {
                    "file_path": str(repo / "docs/feature-b.md"),
                    "content": "# feature B\n",
                }),
                _tool_result("u3", _ts(31)),
                _tool_use("u4", _ts(40), "Edit", {
                    "file_path": str(repo / "src/a.py"),
                    "old_string": "def a(): return 1\n",
                    "new_string": "def a(): return 2\n",
                }),
                _tool_result("u4", _ts(41)),
                _tool_use("u5", _ts(50), "Write", {
                    "file_path": str(repo / "src/b.py"),
                    "content": "def b(): return 'hello'\n",
                }),
                _tool_result("u5", _ts(51)),
            ]
            _make_jsonl(session_dir, "main", records)

            # Manually create the final working-tree state to match
            (repo / "docs").mkdir()
            (repo / "src").mkdir()
            (repo / "docs/feature-a.md").write_text("# feature A\n")
            (repo / "docs/feature-b.md").write_text("# feature B\n")
            (repo / "src/a.py").write_text("def a(): return 2\n")
            (repo / "src/b.py").write_text("def b(): return 'hello'\n")

            # Plan
            jsonls = re_.find_session_jsonls(session_dir)
            assert len(jsonls) == 1
            ops, msgs = re_.extract_timeline(jsonls, repo)
            assert len(ops) == 5  # 4 Writes + 1 Edit
            specs = re_.boundaries_doc_files(ops, "docs/*.md")
            assert len(specs) == 2
            assert "feature-a" in specs[0].name
            assert "feature-b" in specs[1].name

            # Execute (sandbox)
            sandbox = re_.make_sandbox(repo, "HEAD", "claude-replay")
            result = re_.replay(ops, specs, repo, sandbox)
            assert len(result.commits) == 2
            assert result.final_diff_entries == 0, \
                f"sandbox diverges: {result.final_diff_text}"

            # Verify chain
            log = _git(sandbox, "log", "--oneline", capture=True).stdout
            assert "feature-a" in log
            assert "feature-b" in log
        finally:
            re_.project_session_dir = orig


def test_time_gap_strategy():
    """Two batches separated by an idle gap => two commits."""
    op1 = re_.Op(ts=_ts(0), sid="x", name="Write",
                  payload={"file_path": "/abs/foo.txt", "content": ""})
    op2 = re_.Op(ts=_ts(60), sid="x", name="Write",
                  payload={"file_path": "/abs/foo.txt", "content": ""})
    op3 = re_.Op(ts=_ts(60 * 60), sid="x", name="Write",
                  payload={"file_path": "/abs/foo.txt", "content": ""})  # 1h gap
    specs = re_.boundaries_time_gap([op1, op2, op3], gap_minutes=30)
    assert len(specs) == 2


def test_user_approve_strategy():
    msgs = [
        re_.UserMessage(ts=_ts(10), sid="x", text="please proceed"),
        re_.UserMessage(ts=_ts(20), sid="x", text="批准 phase 1"),
        re_.UserMessage(ts=_ts(30), sid="x", text="random comment"),
        re_.UserMessage(ts=_ts(40), sid="x", text="LGTM, ship it"),
    ]
    specs = re_.boundaries_user_approve([], msgs, r"批准|LGTM")
    assert len(specs) == 2


def test_one_shot_strategy():
    specs = re_.boundaries_one_shot([])
    assert len(specs) == 1
    assert specs[0].until_ts == "9999"


def test_recover_file_end_to_end():
    """Lifeline scenario — one file written then edited; reconstruct from JSONL alone."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session_dir = tmp / "sessions"
        out_dir = tmp / "out"
        target_file = "/abs/repo/src/lost.py"
        records = [
            _tool_use("u1", _ts(0), "Write", {"file_path": target_file, "content": "v1\n"}),
            _tool_result("u1", _ts(1)),
            _tool_use("u2", _ts(10), "Edit", {
                "file_path": target_file, "old_string": "v1", "new_string": "v2"}),
            _tool_result("u2", _ts(11)),
            _tool_use("u3", _ts(20), "Edit", {
                "file_path": target_file, "old_string": "v2", "new_string": "v3"}),
            _tool_result("u3", _ts(21)),
        ]
        _make_jsonl(session_dir, "main", records)

        # Use the engine functions directly (mimics CLI)
        jsonls = re_.find_session_jsonls(session_dir)
        ops = sorted(
            [op for op in _collect_ops_for_path(jsonls, target_file)],
            key=lambda o: o.ts,
        )
        assert len(ops) == 3

        # Reconstruct
        content = ""
        for o in ops:
            if o.name == "Write":
                content = o.payload["content"]
            elif o.name == "Edit":
                content = content.replace(o.payload["old_string"], o.payload["new_string"], 1)
        assert content == "v3\n"


def test_recover_file_at_specific_ts():
    """Recover an intermediate version with --at-ts (mid-history snapshot)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session_dir = tmp / "sessions"
        target_file = "/abs/repo/src/lost.py"
        records = [
            _tool_use("u1", _ts(0), "Write", {"file_path": target_file, "content": "v1\n"}),
            _tool_result("u1", _ts(1)),
            _tool_use("u2", _ts(10), "Edit", {
                "file_path": target_file, "old_string": "v1", "new_string": "v2"}),
            _tool_result("u2", _ts(11)),
            _tool_use("u3", _ts(20), "Edit", {
                "file_path": target_file, "old_string": "v2", "new_string": "v3"}),
            _tool_result("u3", _ts(21)),
        ]
        _make_jsonl(session_dir, "main", records)

        # Filter ops with ts <= _ts(15) — should give v2
        jsonls = re_.find_session_jsonls(session_dir)
        ops = [
            op for op in _collect_ops_for_path(jsonls, target_file)
            if op.ts <= _ts(15)
        ]
        ops.sort(key=lambda o: o.ts)
        content = ""
        for o in ops:
            if o.name == "Write":
                content = o.payload["content"]
            elif o.name == "Edit":
                content = content.replace(o.payload["old_string"], o.payload["new_string"], 1)
        assert content == "v2\n"


def test_recover_project_end_to_end():
    """Project resurrection — multiple files reconstructed into a fresh tree."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session_dir = tmp / "sessions"
        out_dir = tmp / "out"
        records = [
            _tool_use("u1", _ts(0), "Write", {
                "file_path": "/abs/myrepo/src/a.py", "content": "a()\n"}),
            _tool_result("u1", _ts(1)),
            _tool_use("u2", _ts(10), "Write", {
                "file_path": "/abs/myrepo/src/b.py", "content": "b()\n"}),
            _tool_result("u2", _ts(11)),
            _tool_use("u3", _ts(20), "Write", {
                "file_path": "/abs/myrepo/README.md", "content": "# myrepo\n"}),
            _tool_result("u3", _ts(21)),
            _tool_use("u4", _ts(30), "Edit", {
                "file_path": "/abs/myrepo/src/a.py",
                "old_string": "a()", "new_string": "a() + 1"}),
            _tool_result("u4", _ts(31)),
        ]
        _make_jsonl(session_dir, "main", records)

        jsonls = re_.find_session_jsonls(session_dir)
        # _collect_ops collects per-file
        from collections import defaultdict
        ops_per_file = defaultdict(list)
        for op in _collect_all_ops(jsonls):
            if op.file_path and op.file_path.startswith("/abs/myrepo/"):
                ops_per_file[op.file_path].append(op)

        assert set(ops_per_file.keys()) == {
            "/abs/myrepo/src/a.py", "/abs/myrepo/src/b.py", "/abs/myrepo/README.md"}

        # Reconstruct each
        out_dir.mkdir()
        for orig_path, ops in ops_per_file.items():
            ops.sort(key=lambda o: o.ts)
            content = ""
            for o in ops:
                if o.name == "Write":
                    content = o.payload["content"]
                elif o.name == "Edit":
                    content = content.replace(
                        o.payload["old_string"], o.payload["new_string"], 1)
            rel = Path(orig_path).relative_to("/abs/myrepo")
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        assert (out_dir / "src/a.py").read_text() == "a() + 1\n"
        assert (out_dir / "src/b.py").read_text() == "b()\n"
        assert (out_dir / "README.md").read_text() == "# myrepo\n"


def _collect_ops_for_path(jsonls, target_path: str):
    """Helper: read JSONLs and emit ops on target_path only."""
    for op in _collect_all_ops(jsonls):
        if op.file_path == target_path:
            yield op


def _collect_all_ops(jsonls):
    """Helper: read JSONLs and emit all file-touching Ops (no repo-root filter)."""
    for path in jsonls:
        sid = path.stem
        with path.open() as fp:
            for line in fp:
                rec = json.loads(line)
                ts = rec.get("timestamp", "")
                msg = rec.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                for block in msg.get("content", []):
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if name not in ("Write", "Edit", "MultiEdit"):
                        continue
                    yield re_.Op(ts=ts, sid=sid, name=name,
                                  payload=block.get("input") or {})
