"""Recover only complete, byte-preserving file reads from session transcripts."""
import json
import os
import re

from .proof import file_proof


def _visible_complete(raw, visible, total):
    if raw == visible:
        return True
    if not isinstance(visible, str):
        return False
    variants = [raw.splitlines(), raw.split("\n")]
    return any(lines and len(lines) == total and visible.splitlines() == [f"{i:6d}→{line}"
                                                   for i, line in enumerate(lines, 1)]
               for lines in variants)


def observations(transcript, root, host="claude"):
    """Read Claude's paired Read results with explicit complete-file metadata.

    Unknown host encodings and transformed, truncated or partial results are rejected.
    """
    if host == "pi":
        return _pi_observations(transcript, root)
    if host == "copilot":
        return _copilot_observations(transcript, root)
    if host != "claude":
        return {}
    calls, found = {}, {}
    try:
        with open(transcript, encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                blocks = (event.get("message") or {}).get("content") or []
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if (event.get("type") == "assistant" and block.get("type") == "tool_use"
                            and block.get("name") == "Read"):
                        calls[block.get("id")] = block.get("input") or {}
                    if (event.get("type") != "user" or len(blocks) != 1
                            or block.get("type") != "tool_result" or block.get("is_error")):
                        continue
                    args = calls.get(block.get("tool_use_id"))
                    meta = event.get("toolUseResult") or {}
                    file = meta.get("file") or {} if isinstance(meta, dict) else {}
                    if not isinstance(args, dict) or not isinstance(file, dict):
                        continue
                    content = file.get("content")
                    path = args.get("file_path")
                    if (meta.get("type") != "text" or not isinstance(path, str)
                            or file.get("filePath") != path
                            or args.get("offset") is not None or args.get("limit") is not None
                            or not isinstance(content, str) or "\ufffd" in content
                            or not _visible_complete(content, block.get("content"),
                                                     file.get("totalLines"))
                            or file.get("truncatedByTokenCap") or file.get("originalSize")
                            or file.get("startLine") != 1
                            or type(file.get("totalLines")) is not int
                            or file.get("numLines") != file.get("totalLines")
                            or file.get("totalLines") not in
                               (len(content.splitlines()), len(content.split("\n")))):
                        continue
                    proof = file_proof(root, path, content.encode("utf-8"), complete=True)
                    if proof:
                        if proof["path"] in found or len(found) < 10:
                            found[proof["path"]] = {"proof": proof, "excerpt": content[:2000]}
    except (OSError, UnicodeError):
        return {}
    return found


def _strict_records(transcript):
    with open(transcript, encoding="utf-8", errors="strict") as stream:
        events = [json.loads(line) for line in stream if line.strip()]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("invalid session record")
    return events


def _pi_observations(transcript, root):
    from ..trace.pi import pi_active_branch
    try:
        entries = _strict_records(transcript)
        header = entries[0] if entries and entries[0].get("type") == "session" else {}
        cwd = header.get("cwd")
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return {}
        calls, found = {}, {}
        branch = pi_active_branch(entries)
        if not branch or branch[0].get("parentId") is not None:
            return {}
        for event in branch:
            if event.get("type") != "message":
                continue
            message = event.get("message") or {}
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant":
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "toolCall" and block.get("name") == "read":
                        calls[block.get("id")] = block.get("arguments")
            elif message.get("role") == "toolResult":
                args = calls.pop(message.get("toolCallId"), None)
                blocks = message.get("content")
                if (message.get("toolName") != "read" or message.get("isError") is not False
                        or message.get("details") not in (None, {})
                        or not isinstance(args, dict) or not isinstance(args.get("path"), str)
                        or "offset" in args or "limit" in args
                        or not isinstance(blocks, list) or len(blocks) != 1
                        or not isinstance(blocks[0], dict) or blocks[0].get("type") != "text"):
                    continue
                text = blocks[0].get("text")
                if (not isinstance(text, str) or "\ufffd" in text
                        or len(text.encode("utf-8")) >= 50 * 1024
                        or len(text.splitlines()) >= 2000
                        or re.search(r"\[(?:Showing lines |\d+ more lines in file\.|Line \d+ is )", text)):
                    continue
                proof = file_proof(root, os.path.join(cwd, args["path"]),
                                   text.encode("utf-8"), complete=True)
                if proof and (proof["path"] in found or len(found) < 10):
                    found[proof["path"]] = {"proof": proof, "excerpt": text[:2000]}
        return found
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def _copilot_observations(transcript, root):
    """Read the verified Copilot 1.0.105 event format, requiring truncation telemetry."""
    calls, found, cwd, supported = {}, {}, None, False
    try:
        for event in _strict_records(transcript):
            data = event.get("data") or {}
            if not isinstance(data, dict):
                continue
            kind = event.get("type")
            if kind == "session.start":
                supported = data.get("copilotVersion") == "1.0.105"
                cwd = (data.get("context") or {}).get("cwd")
            elif kind == "tool.execution_start" and data.get("toolName") == "view":
                calls[data.get("toolCallId")] = data.get("arguments")
            elif kind == "tool.execution_complete":
                args = calls.pop(data.get("toolCallId"), None)
                telemetry = data.get("toolTelemetry") or {}
                props = telemetry.get("properties") or {}
                metrics = telemetry.get("metrics") or {}
                result = data.get("result") or {}
                if (not supported or not isinstance(cwd, str) or not os.path.isabs(cwd)
                        or not isinstance(args, dict) or not isinstance(args.get("path"), str)
                        or set(args) != {"path"} or data.get("success") is not True
                        or not isinstance(props, dict) or not isinstance(metrics, dict)
                        or not isinstance(result, dict) or props.get("viewType") != "file"
                        or props.get("command") != "view" or props.get("largeOutputAvoided")):
                    continue
                text = result.get("content")
                inputs = json.loads(props.get("inputs", "null"))
                options = json.loads(props.get("options", "null"))
                if (not isinstance(text, str) or "\ufffd" in text or not isinstance(inputs, list)
                        or set(inputs) != {"path", "command"}
                        or options != {"truncateBasedOn": "tokenCount", "truncateStyle": "middle"}
                        or len(text.encode("utf-8")) >= 20480
                        or text.startswith("File too large to read at once")
                        or type(metrics.get("resultLength")) is not int
                        or type(metrics.get("resultForLlmLength")) is not int
                        or metrics["resultLength"] != metrics["resultForLlmLength"]
                        or metrics["resultLength"] != len(text.encode("utf-16-le")) // 2):
                    continue
                proof = file_proof(root, os.path.join(cwd, args["path"]),
                                   text.encode("utf-8"), complete=True)
                if proof and (proof["path"] in found or len(found) < 10):
                    found[proof["path"]] = {"proof": proof, "excerpt": text[:2000]}
        return found
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return {}
