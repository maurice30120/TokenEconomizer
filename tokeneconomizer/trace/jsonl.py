"""Reading a JSONL log line by line, skipping what does not parse; and the one timestamp
parse the hosts' logs share, so their times compare across hosts."""
import json
from datetime import datetime


def lines(path):
    """Non-empty, stripped lines of a text file; nothing when it cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield line
    except OSError:
        return


def epoch(timestamp):
    """Epoch seconds of an ISO-8601 timestamp, as every host writes it
    (`2026-11-24T10:58:58.434Z`); None when it is absent or does not parse."""
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp[:-1] + "+00:00"
                                      if timestamp.endswith("Z") else timestamp).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def records(path):
    """Each line of a JSONL file that parses to a JSON object."""
    for line in lines(path):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev
