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


def test_a_read_crossing_a_declaration_proves_only_that_whole_symbol(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proofs_in, verify_proof
    data = b"def alpha():\n    return 1\n\ndef beta():\n    return 2\n"
    (tmp_path / "source.py").write_bytes(data)
    # the read saw one line inside `alpha`, and nothing of `beta`
    proofs = symbol_proofs_in(tmp_path, "source.py", data, 2, 2)
    assert list(proofs) == ["alpha"]
    assert proofs["alpha"]["kind"] == "symbol" and proofs["alpha"]["path"] == "source.py"
    assert verify_proof(tmp_path, proofs["alpha"])
    # the proof is over the whole declaration: an unread line of it still invalidates
    (tmp_path / "source.py").write_bytes(data.replace(b"return 1", b"return 9"))
    assert not verify_proof(tmp_path, proofs["alpha"])
    (tmp_path / "source.py").write_bytes(data.replace(b"    return 1", b"    return 1  # why"))
    assert verify_proof(tmp_path, proofs["alpha"])


def test_a_read_crossing_no_declaration_proves_nothing(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proofs_in
    data = b"# header\nimport os\n\ndef alpha():\n    return 1\n"
    (tmp_path / "source.py").write_bytes(data)
    assert symbol_proofs_in(tmp_path, "source.py", data, 1, 2) == {}
    assert symbol_proofs_in(tmp_path, "source.py", data, 3, 3) == {}
    assert list(symbol_proofs_in(tmp_path, "source.py", data, 4, 4)) == ["alpha"]


def test_decorators_belong_to_the_symbol_a_read_crossed(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proofs_in, verify_proof
    data = b"@cached\ndef alpha():\n    return 1\n"
    (tmp_path / "source.py").write_bytes(data)
    # the decorator line alone crosses the declaration, and the proof covers the decorator
    proof = symbol_proofs_in(tmp_path, "source.py", data, 1, 1)["alpha"]
    assert verify_proof(tmp_path, proof)
    (tmp_path / "source.py").write_bytes(data.replace(b"@cached", b"@chached"))
    assert not verify_proof(tmp_path, proof)


def test_a_read_inside_a_nested_symbol_proves_both(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proofs_in
    data = b"def outer():\n    def inner():\n        return 1\n    return inner\n"
    (tmp_path / "source.py").write_bytes(data)
    assert sorted(symbol_proofs_in(tmp_path, "source.py", data, 3, 3)) == ["inner", "outer"]


def test_an_ambiguous_or_unparsable_file_proves_nothing(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proofs_in
    duplicate = b"def alpha():\n    return 1\n\ndef alpha():\n    return 2\n"
    (tmp_path / "source.py").write_bytes(duplicate)
    assert symbol_proofs_in(tmp_path, "source.py", duplicate, 2, 2) == {}
    broken = b"def alpha(:\n    return 1\n"
    assert symbol_proofs_in(tmp_path, "broken.py", broken, 1, 1) == {}
    assert symbol_proofs_in(tmp_path, "notes.txt", b"def alpha():\n    return 1\n", 1, 1) == {}
    assert symbol_proofs_in(tmp_path, "source.py", duplicate, 4, 99) == {}


def test_a_typescript_exported_function_is_a_symbol_too(tmp_path):
    from tokeneconomizer.knowledge.proof import symbol_proofs_in, verify_proof
    data = (b"export function alpha(): number {\n  return 1;\n}\n\nexport function beta() {\n"
            b"  return 2;\n}\n")
    (tmp_path / "code.ts").write_bytes(data)
    proofs = symbol_proofs_in(tmp_path, "code.ts", data, 3, 4)
    assert list(proofs) == ["alpha"]
    assert verify_proof(tmp_path, proofs["alpha"])
    (tmp_path / "code.ts").write_bytes(data.replace(b"return 1", b"return 3"))
    assert not verify_proof(tmp_path, proofs["alpha"])
