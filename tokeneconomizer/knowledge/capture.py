"""The file bytes a Pi `read` returned, kept for the fold that must prove things about them.

A Pi read may return only part of a file (`offset` and/or `limit`), and its result is stored
in the session log as text: by the time the session is folded, the file may have changed, and
re-reading it then would prove nothing about what the model actually saw. So the hook keeps a
copy of the file's bytes as they were at the instant of the read, and the fold only accepts a
partial read whose logged text still matches that copy.

`match_read` is the contract: given the tool result and the candidate file, it recovers exactly
one line window whose bytes are the result's body, and validates the footer Pi appends while
content remains past that window. Anything it cannot pin down -- a lossy result, a footer whose
counts disagree, a window that is not there -- yields no match, and therefore no proof.
"""
import hashlib
import json
import os
import re
import shutil
import time

MAX_CAPTURE_BYTES = 8 * 1024 * 1024   # one captured file
MAX_CAPTURES = 12                     # captured files kept per session
MAX_SESSION_BYTES = 8 * 1024 * 1024   # captured bytes kept per session
EXPIRE_SECONDS = 7 * 24 * 3600        # older session directories go

# Pi appends one footer while content remains, and only then: `<body>\n\n[<footer>]`. The
# trailing empty line of a newline-terminated file is a line, which is why a five-line file
# reports `[4 more lines in file. Use offset=3 ...]` after two lines.
_FOOTER = re.compile(
    r"\n\n\[(?:(?P<showing>Showing lines (?P<first>\d+)-(?P<last>\d+) of (?P<total>\d+)"
    r"(?: \([^)]*KB limit\))?)|(?:(?P<more>\d+) more lines in file))\. "
    r"Use offset=(?P<next>\d+) to continue\.\]\Z")
# The first line alone is over the byte limit: the result carries no content to match.
_OVERSIZE = re.compile(r"\A\[Line \d+ is [^\]]*exceeds [\d.]+KB limit")


def match_read(text, data, offset=None, limit=None):
    """The line window `text` reports, read from `data`; None when it is not pinned down."""
    if not isinstance(text, str) or not isinstance(data, bytes) or "\ufffd" in text \
            or _OVERSIZE.match(text):
        return None
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        return None
    total = len(lines)
    start = 1 if offset is None else offset
    if type(start) is not int or start < 1 or start > total \
            or (limit is not None and (type(limit) is not int or limit < 0)):
        return None
    readings = [(text, None)]
    footer = _FOOTER.search(text)
    if footer:
        # The same text may be the file's own last lines: keep both readings, accept one only.
        readings.append((text[:footer.start()], footer))
    found = [m for m in (_window(lines, body, tail, start, total, limit)
                         for body, tail in readings) if m is not None]
    return found[0] if len(found) == 1 else None


def _window(lines, body, footer, start, total, limit):
    # Walk the candidate ends once, tracking how far into `body` the joined lines reach: adding
    # a line only ever lengthens the join, so the walk can stop as soon as the body's end is
    # passed. Comparing in place keeps the whole search over the file's bytes, where rebuilding
    # each prefix made a partial read of a large file quadratic (and stalled the hook).
    end, pos, found = start, 0, None
    while end <= total:
        if end > start:
            if pos >= len(body) or body[pos] != "\n":
                break
            pos += 1
        line = lines[end - 1]
        if not body.startswith(line, pos):
            break
        pos += len(line)
        if pos >= len(body):
            found = end if pos == len(body) else None
            break
        end += 1
    if found is None:
        return None
    end = found
    if footer is None:
        if end != total or (limit is not None and limit < end - start + 1):
            return None
    elif int(footer.group("next")) != end + 1:
        return None
    elif footer.group("showing") is not None:
        if (int(footer.group("first")) != start or int(footer.group("last")) != end
                or int(footer.group("total")) != total
                or (limit is not None and end - start + 1 > limit)):
            return None
    elif int(footer.group("more")) != total - end:
        return None
    return {"offset": start, "lines": end - start + 1, "total_lines": total,
            "complete": start == 1 and end == total}


def session_dir(store, session_id):
    """Where one session's captures live: the hook that writes them and the fold share a store."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "__", str(session_id)).rstrip(". ") or "session"
    return store.path("knowledge_captures", name)


def record(store, session_id, ctx, payload):
    """Keep the bytes this `read` returned. Fail-open: a capture never breaks the agent."""
    try:
        _record(store, session_id, ctx, payload)
    except Exception:
        pass


def _record(store, session_id, ctx, payload):
    response, args = payload.get("tool_response"), payload.get("tool_input")
    if (payload.get("tool_name") != "read" or not isinstance(response, dict)
            or response.get("isError") is not False or not isinstance(args, dict)):
        return
    offset = args.get("offset")
    limit = args.get("limit")
    if ("offset" not in args and "limit" not in args) or not isinstance(args.get("path"), str) \
            or ("offset" in args and _count(offset, 1) is None) \
            or ("limit" in args and _count(limit, 0) is None):
        return
    tool_use_id = payload.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return
    root = os.path.realpath(ctx.repo.root)
    target = os.path.realpath(os.path.join(root, args["path"]))
    if os.path.commonpath([root, target]) != root or not os.path.isfile(target):
        return
    if os.path.getsize(target) > MAX_CAPTURE_BYTES:
        return
    with open(target, "rb") as stream:
        data = stream.read(MAX_CAPTURE_BYTES + 1)
    if len(data) > MAX_CAPTURE_BYTES:
        return
    match = match_read(response.get("content"), data, offset, limit)
    if match is None:
        return
    _store_capture(store, session_id, {
        "tool_use_id": tool_use_id, "path": os.path.relpath(target, root),
        "sha256": hashlib.sha256(data).hexdigest(), "offset": match["offset"],
        "lines": match["lines"]}, data)


def _count(value, floor):
    return value if type(value) is int and value >= floor else None


def _store_capture(store, session_id, entry, data):
    directory = session_dir(store, session_id)
    _expire(store)
    index = _read_index(directory)
    # The same call may be delivered again (a hook replay): the first capture is the closest
    # to the read, so a later one never replaces it.
    if any(c.get("tool_use_id") == entry["tool_use_id"] for c in index):
        return
    captures = list(index)
    known = {c.get("sha256") for c in captures}
    if entry["sha256"] not in known:
        if len(known) >= MAX_CAPTURES or _bytes_on_disk(directory) + len(data) > MAX_SESSION_BYTES:
            return
        _write_bytes(os.path.join(directory, entry["sha256"] + ".bin"), data)
    captures.append(entry)
    store.write(os.path.join(os.path.relpath(directory, store.base), "index.json"),
                {"captures": captures})


def _read_index(directory):
    try:
        with open(os.path.join(directory, "index.json"), encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, ValueError):
        return []
    captures = document.get("captures") if isinstance(document, dict) else None
    return [c for c in captures if isinstance(c, dict)] if isinstance(captures, list) else []


def _write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temporary, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _bytes_on_disk(directory):
    total = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.endswith(".bin") and entry.is_file():
                    total += entry.stat().st_size
    except OSError:
        return 0
    return total


def _expire(store):
    parent = store.path("knowledge_captures")
    cutoff = time.time() - EXPIRE_SECONDS
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
    except OSError:
        pass


def load(directory):
    """The captures of one session directory, by the tool call that made them."""
    out = {}
    for entry in _read_index(directory):
        try:
            with open(os.path.join(directory, entry["sha256"] + ".bin"), "rb") as stream:
                data = stream.read()
            record = {"path": entry["path"], "bytes": data, "offset": entry["offset"],
                      "lines": entry["lines"]}
        except (OSError, KeyError, TypeError):
            continue
        if (isinstance(record["path"], str) and isinstance(record["offset"], int)
                and isinstance(record["lines"], int)):
            out[entry["tool_use_id"]] = record
    return out


def discard(directory):
    """Forget one session's captures: the fold has taken what it can from them."""
    shutil.rmtree(directory, ignore_errors=True)
