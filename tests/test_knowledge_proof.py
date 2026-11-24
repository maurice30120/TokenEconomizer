from tokeneconomizer.knowledge.proof import file_proof, verify_file


def test_file_proof_attests_observed_bytes_and_can_recover(tmp_path):
    path = tmp_path / "source.txt"
    path.write_bytes(b"original\n")
    proof = file_proof(tmp_path, "source.txt", b"original\n", complete=True)
    assert proof is not None
    assert verify_file(tmp_path, proof)
    path.write_bytes(b"changed\n")
    assert not verify_file(tmp_path, proof)
    path.unlink()
    assert not verify_file(tmp_path, proof)
    path.write_bytes(b"original\n")
    assert verify_file(tmp_path, proof)


def test_partial_or_unverifiable_observation_is_not_a_proof(tmp_path):
    assert file_proof(tmp_path, "source.txt", b"prefix", complete=False) is None
    assert file_proof(tmp_path, "source.txt", "text", complete=True) is None
    assert file_proof(tmp_path, "../outside", b"data", complete=True) is None


def test_malformed_or_cyclic_proof_fails_closed(tmp_path):
    (tmp_path / "cycle").symlink_to("cycle")
    assert not verify_file(tmp_path, {"path": "cycle", "sha256": "x"})
    assert not verify_file(tmp_path, {})


def test_symbol_proof_tracks_code_but_not_comments_or_other_symbols(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proof, verify_proof
    path = tmp_path / "source.py"
    original = b"def alpha():\n    # old\n    return 1\n\ndef beta():\n    return 2\n"
    path.write_bytes(original)
    proof = symbol_proof(tmp_path, "source.py", original, "alpha")
    assert proof and verify_proof(tmp_path, proof)
    path.write_bytes(original.replace(b"# old", b"# new").replace(b"return 2", b"return 3"))
    assert verify_proof(tmp_path, proof)
    path.write_bytes(original.replace(b"return 1", b"return 9"))
    assert not verify_proof(tmp_path, proof)


def test_multiple_languages_and_ambiguity(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proof, verify_proof
    examples = {"code.js": b"function foo() { return 1; }\n", "code.go": b"package main\nfunc foo() int { return 1 }\n", "code.rs": b"fn foo() -> i32 { 1 }\n", "code.c": b"int foo() { return 1; }\n", "code.java": b"class A { int foo() { return 1; } }\n"}
    for filename, data in examples.items():
        (tmp_path / filename).write_bytes(data)
        proof = symbol_proof(tmp_path, filename, data, "foo")
        assert proof and verify_proof(tmp_path, proof), filename
    duplicate = b"def foo(): pass\ndef foo(): pass\n"
    assert symbol_proof(tmp_path, "code.py", duplicate, "foo") is None
    assert symbol_proof(tmp_path, "code.unknown", b"foo", "foo") is None


def test_missing_parser_invalidates_existing_symbol(tmp_path, monkeypatch):
    from tokeneconomizer.knowledge.proof import symbol_proof, verify_proof
    import tree_sitter_language_pack
    data = b"def foo():\n    return 1\n"
    (tmp_path / "code.py").write_bytes(data)
    proof = symbol_proof(tmp_path, "code.py", data, "foo")
    assert proof
    def unavailable(*args):
        raise LookupError("unavailable")
    monkeypatch.setattr(tree_sitter_language_pack, "get_parser", unavailable)
    assert not verify_proof(tmp_path, proof)
