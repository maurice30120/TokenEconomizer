"""Recover only complete, byte-preserving file reads from session transcripts."""
import json

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


def observations(transcript, root):
    """Read Claude's paired Read results with explicit complete-file metadata.

    Unknown host encodings and transformed, truncated or partial results are rejected.
    """
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
                            or not isinstance(content, str)
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
