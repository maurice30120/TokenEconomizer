"""`scripts/knowledge_digest_measure.py`: the harness behind `rapport-campagne-341.md`,
which lives at the root of the workspace this repository is checked out in.

It runs on the control trace the harness generates itself, so the test needs no Pi session log,
no baseline checkout and no model call. The control trace is also the witness the report cites for
the 16 000-character cap: its first sequence keeps one read, stops at a 20 400-character one and
loses a 120-character one that would have fitted, and its second opens with a 17 000-character
read and keeps nothing.
"""
import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "knowledge_digest_measure.py")


def _load():
    spec = importlib.util.spec_from_file_location("knowledge_digest_measure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _load()


@pytest.fixture(scope="module")
def report(harness, tmp_path_factory):
    directory = str(tmp_path_factory.mktemp("control"))
    traces, workspace = harness.write_control(directory)
    return harness.measure(traces, workspace, "current")


def test_the_control_trace_folds_both_work_sequences(report):
    (trace,) = report["traces"]
    assert report["arm"]["digest"] is True
    # What the log shows, whichever arm reads it.
    assert (trace["prompts"], trace["reads"], trace["paths"]) == (2, 4, 4)
    assert trace["session"] == "control"
    assert trace["tick"] == {"cadence": False, "sources": True, "ran": False}
    assert trace["state"] == {"before": {"sessions": 0, "last_propose": -1, "opt_tokens": 0.0},
                              "after": {"sessions": 1, "last_propose": -1, "opt_tokens": 0.0}}


def test_the_report_carries_every_metric_the_ticket_asks_for(report):
    (trace,) = report["traces"]
    assert trace["digest"]["catalogue"] == {"entries": 1, "paths": 1, "repeated": 0}
    assert trace["digest"]["reads_kept"] == 1
    assert trace["digest"]["sequences"] == 2 and trace["digest"]["window_sequences"] == 2
    assert trace["digest"]["sequence_char_budget"] == 16_000
    assert trace["digest"]["sequences_budget"] == 8
    # Four reads, one kept: the first sequence stops at its second unit and the second keeps
    # nothing at all.
    assert trace["digest"]["retention"] == {"units": 4, "kept": 1, "dropped": 3, "overflow": 2,
                                            "windowed_out": 0, "windowed_units": 0,
                                            "max_used": 820, "dropped_chars": 37_538}
    # No comment attaches on Pi: every assistant message that carries text also carries a call.
    assert trace["comments"] == {"entries": 0, "occurrences": 0, "chars": 0}
    blocks = trace["prompt"]["blocks"]
    assert list(blocks) == ["native", "mandate", "sequences", "catalogue", "comments", "signals"]
    assert blocks["native"] == 0 and blocks["mandate"] > 0
    assert trace["prompt"]["chars"] == sum(blocks.values())
    assert trace["prompt"]["tokens"] == (trace["prompt"]["chars"] + 3) // 4
    assert 0 < trace["observation_chars"] < trace["prompt"]["chars"]


def test_admission_walks_from_admitted_to_duplicate_to_stale(report):
    (trace,) = report["traces"]
    assert trace["admission"] == {"entry": {"ref": "control/0.0"}, "path": "alpha.txt",
                                  "admitted": True, "reason": "admitted",
                                  "duplicate": "duplicate", "stale": "stale-proof"}


def test_the_harness_reports_the_cadence_and_the_window_across_sessions(harness, tmp_path):
    """Two sessions, one proposal tick: the first fold is not due (the default cadence is three
    sessions), the second is, and its prompt is the one the stub sees. The window then holds both
    sessions' sequences, which is what a multisession digest is."""
    traces, workspace = harness.write_control(str(tmp_path / "pair"))
    traces += harness.write_control(str(tmp_path / "pair"), session="control-2")[0]
    report = harness.measure(traces, workspace, "current")
    assert [trace["tick"] for trace in report["traces"]] == [
        {"cadence": False, "sources": True, "ran": False},
        {"cadence": True, "sources": True, "ran": True}]
    assert report["totals"]["ticks"] == {"cadence": 1, "sources": 2, "ran": 1}
    last = report["traces"][-1]["digest"]
    assert last["window_sequences"] == 4 and last["sessions"] == 2


def test_the_same_traces_give_the_same_report(harness, tmp_path):
    traces, workspace = harness.write_control(str(tmp_path / "one"))
    again, elsewhere = harness.write_control(str(tmp_path / "two"))
    first = harness.measure(traces, workspace, "current")
    second = harness.measure(again, elsewhere, "current")
    assert first["totals"] == second["totals"]
    assert [t["prompt"] for t in first["traces"]] == [t["prompt"] for t in second["traces"]]
    assert [t["digest"] for t in first["traces"]] == [t["digest"] for t in second["traces"]]
    assert [t["admission"] for t in first["traces"]] == [t["admission"] for t in second["traces"]]


def test_the_contradiction_probe_retires_the_fact_it_admitted(report):
    """The lifecycle run end to end: one folded session the detector confirms on, a Knowledge
    admitted on its proofs, then a session the same detector contradicts -- the fact goes
    `RETIRED` and `render()` stops returning it."""
    (trace,) = report["traces"]
    probe = trace["probes"]["contradiction"]
    assert probe["measured"] is True
    assert probe["confirmed"] == ["probe-confirm"]
    assert probe["contradicted"] == ["probe-contradict"]
    assert probe["before"] == {"state": "ACTIVE", "rendered": True}
    assert probe["after"] == {"state": "RETIRED", "rendered": False}
    assert probe["expected"] == "RETIRED" and probe["holds"] is True
    assert report["totals"]["probes"]["contradiction"] == {
        "measured": 1, "not measured": 0, "retired": 1,
        "rendered after retirement": 0, "reasons": {}}


def test_a_probe_that_cannot_run_is_not_measured_never_zero(harness, tmp_path):
    """On traces where no observation can be cited (nothing retained, or a proof that no longer
    verifies) the probe says `not measured` with its reason, and the summary line says so instead
    of printing a zero that would read as "no contradiction found"."""
    from tokeneconomizer.knowledge.stage import Knowledge
    stage = Knowledge("repo")
    stage.workspace = str(tmp_path)
    assert harness._contradiction_probe(stage, str(tmp_path), True) == {
        "measured": False, "reason": "no observation offered"}
    assert harness._contradiction_probe(stage, str(tmp_path), False) == {
        "measured": False, "reason": "the previous mechanism stores no sequence digest"}
    totals = harness._probe_totals([{"probes": {"contradiction": {
        "measured": False, "reason": "no observation offered"}}}])
    assert harness._probe_line(totals) == (
        "contradiction probe: not measured (1 fold(s); no observation offered x1)")
    assert harness._probe_line(None) == (
        "contradiction probe: not measured (0 fold(s); no reason recorded)")
