import json

from tokeneconomizer.knowledge.observation import observations


def test_recorded_complete_read_preserves_observed_version(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("new version\n")
    events = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": str(path)}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r1", "content": "old version\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": str(path), "content": "old version\n", "startLine": 1, "numLines": 1, "totalLines": 1}}},
    ]
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(map(json.dumps, events)))
    found = observations(transcript, tmp_path)
    assert found["source.txt"]["proof"]["sha256"] == "6e7b43edb0cd439076a2dab27515ed5d563dda0acc5639ae1f6c922d92d7871c"


def test_partial_truncated_and_failed_reads_are_not_evidence(tmp_path):
    path = str(tmp_path / "source.txt")
    transcript = tmp_path / "session.jsonl"
    use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": path}}]}}
    result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "prefix\n"}]}, "toolUseResult": {"type": "text", "file": {"filePath": path, "content": "prefix\n", "startLine": 1, "numLines": 1, "totalLines": 2}}}
    transcript.write_text("\n".join(map(json.dumps, [use, result])))
    assert observations(transcript, tmp_path) == {}
    result["toolUseResult"]["file"]["totalLines"] = 1
    result["message"]["content"][0]["content"] = "truncated"
    transcript.write_text("\n".join(map(json.dumps, [use, result])))
    assert observations(transcript, tmp_path) == {}
    result["message"]["content"][0].update(content="prefix\n", is_error=True)
    transcript.write_text("\n".join(map(json.dumps, [use, result])))
    assert observations(transcript, tmp_path) == {}


def test_numbered_model_visible_read_matches_complete_raw_result(tmp_path):
    path = str(tmp_path / "source.txt")
    transcript = tmp_path / "session.jsonl"
    use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": path}}]}}
    result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r", "content": "     1→hello\n     2→world"}]}, "toolUseResult": {"type": "text", "file": {"filePath": path, "content": "hello\nworld\n", "startLine": 1, "numLines": 2, "totalLines": 2}}}
    transcript.write_text("\n".join(map(json.dumps, [use, result])))
    assert "source.txt" in observations(transcript, tmp_path)
    result["toolUseResult"]["file"]["truncatedByTokenCap"] = True
    transcript.write_text("\n".join(map(json.dumps, [use, result])))
    assert observations(transcript, tmp_path) == {}
