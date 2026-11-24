"""The bytes a Pi `read` returned, matched against the file they came from.

Each case reproduces a result the real Pi 1.6.0 `read` tool produced for the call named in
its docstring: the body is the file's own bytes, and the footer is added only while content
remains past it.
"""
import os
import time
from types import SimpleNamespace

import pytest

from tokeneconomizer.knowledge.capture import discard, load, match_read, record, session_dir
from tokeneconomizer.plugin.store import Store

FIVE = b"line one\nline two\nline three\nline four\nline five\n"


def lines_file(count):
    """`count` real lines, each newline-terminated: Pi counts `count + 1` of them."""
    return "".join(f"line {i}\n" for i in range(1, count + 1)).encode("utf-8")


def test_offset_alone_reads_to_the_end_without_a_footer():
    assert match_read("line two\nline three\nline four\nline five\n", FIVE, 2) == {
        "offset": 2, "lines": 5, "total_lines": 6, "complete": False}


def test_limit_alone_reports_the_lines_it_did_not_read():
    assert match_read("line one\nline two\n\n[4 more lines in file. Use offset=3 to continue.]",
                      FIVE, None, 2) == {
        "offset": 1, "lines": 2, "total_lines": 6, "complete": False}


def test_offset_and_limit_together():
    assert match_read(
        "line two\nline three\n\n[3 more lines in file. Use offset=4 to continue.]",
        FIVE, 2, 2) == {"offset": 2, "lines": 2, "total_lines": 6, "complete": False}


def test_the_trailing_empty_line_counts_as_one_more_line_than_the_reader_sees():
    assert match_read(
        "line one\nline two\nline three\nline four\nline five\n"
        "\n[1 more lines in file. Use offset=6 to continue.]", FIVE, 1, 5) == {
        "offset": 1, "lines": 5, "total_lines": 6, "complete": False}


def test_a_limit_past_the_end_adds_no_footer():
    assert match_read("line two\nline three\nline four\nline five\n", FIVE, 2, 99) == {
        "offset": 2, "lines": 5, "total_lines": 6, "complete": False}


def test_a_read_that_covers_the_whole_file_is_complete_whatever_its_arguments():
    assert match_read("no trailing", b"no trailing", 1, 1) == {
        "offset": 1, "lines": 1, "total_lines": 1, "complete": True}
    assert match_read(FIVE.decode(), FIVE, 1, 99)["complete"] is True


def test_the_default_read_of_a_long_file_is_truncated_at_two_thousand_lines():
    data = lines_file(3000)
    body = "\n".join(data.decode().split("\n")[:2000])
    found = match_read(body + "\n\n[Showing lines 1-2000 of 3001. Use offset=2001 to continue.]",
                       data)
    assert found == {"offset": 1, "lines": 2000, "total_lines": 3001, "complete": False}


def test_the_line_window_footer_carries_the_byte_limit():
    data = lines_file(3000)
    body = "\n".join(data.decode().split("\n")[:2000])
    found = match_read(
        body + "\n\n[Showing lines 1-2000 of 3001 (50.0KB limit). Use offset=2001 to continue.]",
        data)
    assert found == {"offset": 1, "lines": 2000, "total_lines": 3001, "complete": False}


def test_a_late_offset_keeps_its_numbering():
    data = lines_file(3000)
    body = "\n".join(data.decode().split("\n")[1989:2009])
    assert match_read(body + "\n\n[992 more lines in file. Use offset=2010 to continue.]",
                      data, 1990, 20) == {
        "offset": 1990, "lines": 20, "total_lines": 3001, "complete": False}


@pytest.mark.parametrize("text, offset, limit", [
    # the first line is too large: the result carries no content at all
    ("[Line 3 is 60.0KB, exceeds 50.0KB limit. Use bash: sed -n '3p']", None, None),
    # a lossy decode of the file it claims to come from
    ("line two\ufffd\nline three\n", 2, None),
    # a footer whose counts do not hold
    ("line one\nline two\n\n[9 more lines in file. Use offset=3 to continue.]", None, None),
    # a body that is not in the file
    ("line two\nline NINE\n", 2, None),
    # out of bounds
    ("line five\n", 9, None),
    ("line one\n", 0, None),
    # a limit stopped before the end but no footer says so
    ("line one\nline two", 1, 2),
    ("line one\nline two", None, None),
])
def test_an_unmatching_result_is_never_captured(text, offset, limit):
    assert match_read(text, FIVE, offset, limit) is None


def test_a_file_that_ends_in_a_footer_is_ambiguous_and_refused():
    data = b"observed\n\n[2 more lines in file. Use offset=2 to continue.]"
    assert match_read(data.decode(), data) is None


def test_a_read_wider_than_its_limit_is_refused():
    data = lines_file(3000)
    body = "\n".join(data.decode().split("\n")[:1500])
    text = body + "\n\n[Showing lines 1-1500 of 3001. Use offset=1501 to continue.]"
    assert match_read(text, data, 1, 1000) is None
    assert match_read(text, data, 1, 1500) is not None


def test_an_empty_file_is_a_complete_read_of_one_empty_line():
    assert match_read("", b"") == {"offset": 1, "lines": 1, "total_lines": 1, "complete": True}


# ---- capture store -----------------------------------------------------------------------
def partial_read_payload(root, path="source.py", limit=1, tool_use_id="call_1",
                         is_error=False, tool="read"):
    data = (root / path).read_bytes()
    body = "\n".join(data.decode("utf-8").split("\n")[:limit])
    rest = len(data.decode("utf-8").split("\n")) - limit
    text = body + f"\n\n[{rest} more lines in file. Use offset={limit + 1} to continue.]"
    return {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": tool,
            "tool_use_id": tool_use_id,
            "tool_input": {"path": path, "limit": limit},
            "tool_response": {"content": text, "isError": is_error}}


def workspace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "source.py").write_text("def target():\n    return 1\n")
    return root


def test_record_keeps_the_bytes_the_read_returned(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    record(store, "s1", ctx, partial_read_payload(root))
    captured = load(session_dir(store, "s1"))
    assert captured == {"call_1": {"path": "source.py",
                                   "bytes": (root / "source.py").read_bytes(),
                                   "offset": 1, "lines": 1}}


def test_record_dedupes_the_bytes_and_keeps_one_entry_per_read(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    record(store, "s1", ctx, partial_read_payload(root, tool_use_id="a"))
    record(store, "s1", ctx, partial_read_payload(root, tool_use_id="b"))
    captured = load(session_dir(store, "s1"))
    assert sorted(captured) == ["a", "b"]
    assert len([n for n in (tmp_path / "state").glob("knowledge_captures/s1/*.bin")]) == 1


def test_record_refuses_what_it_cannot_vouch_for(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    (root / "other.py").write_text("x\n")
    payload = partial_read_payload(root)
    outside = dict(payload, tool_input={"path": "../outside.py", "limit": 1})
    changed = dict(payload, tool_response={"content": "def other():\n", "isError": False})
    unknown = dict(payload, tool_response={"content": "nope", "isError": True})
    shell = dict(payload, tool_name="bash", tool_input={"command": "head -1 source.py"})
    (tmp_path / "outside.py").write_text("def outside():\n    pass\n")
    for bad in (outside, changed, unknown, shell,
                dict(payload, tool_input={"path": "source.py"})):
        record(store, "s1", ctx, bad)
    assert load(session_dir(store, "s1")) == {}


def test_record_is_fail_open(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    payload = partial_read_payload(root)
    (root / "source.py").write_bytes(b"\xff\xfe\x00def")
    record(store, "s1", ctx, payload)
    assert load(session_dir(store, "s1")) == {}
    (root / "source.py").write_text("def target():\n    return 1\n")
    ctx.repo = None                       # anything at all may go wrong: the hook still answers
    record(store, "s1", ctx, payload)
    assert load(session_dir(store, "s1")) == {}


def test_capture_is_bounded_per_session_and_purged(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    for i in range(13):
        (root / f"m{i}.py").write_text("".join(f"line {n}\n" for n in range(1, i + 3)))
        record(store, "s1", ctx, partial_read_payload(root, path=f"m{i}.py", tool_use_id=f"r{i}"))
    assert len(load(session_dir(store, "s1"))) == 12
    stale = tmp_path / "state" / "knowledge_captures" / "old"
    stale.mkdir(parents=True)
    (stale / "index.json").write_text("{}")
    old = time.time() - 8 * 24 * 3600
    os.utime(stale, (old, old))
    record(store, "s2", ctx, partial_read_payload(root, tool_use_id="fresh"))
    assert sorted(p.name for p in (tmp_path / "state" / "knowledge_captures").iterdir()) == ["s1", "s2"]


def test_discard_removes_the_session_directory(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    record(store, "s1", ctx, partial_read_payload(root))
    discard(session_dir(store, "s1"))
    assert load(session_dir(store, "s1")) == {}
    discard(session_dir(store, "s1"))     # already gone: still no error


def test_a_replayed_hook_never_replaces_the_capture_of_the_read(tmp_path):
    root, store = workspace(tmp_path), Store(str(tmp_path / "state"))
    ctx = SimpleNamespace(repo=SimpleNamespace(root=str(root)))
    payload = partial_read_payload(root)
    record(store, "s1", ctx, payload)
    # the same call delivered again once the file has changed under it
    (root / "source.py").write_text("def target():\n    return 2\n")
    record(store, "s1", ctx, payload)
    captured = load(session_dir(store, "s1"))["call_1"]
    assert captured["bytes"] == b"def target():\n    return 1\n"
