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
