"""The injected block: one budget over both layers, and the credit for what it delivered.

The caps a `config` documents (`microskills_max_facts`, `microskills_max_tokens`) apply to
the block the agent receives, whatever layers compose it, and the block says which facts it
carries so the fold can credit the facts a session was actually given.
"""
from tokeneconomizer.microskills import Distiller, EnvFactsDistiller
from tokeneconomizer.microskills.distiller import Fact
from tokeneconomizer.microskills.stage import ComposedDistiller


# ---- a layer double: the composition is what is under test here --------------------------
class _Layer:
    def __init__(self, header, lines):
        self._header = header
        self._lines = list(lines)
        self.last_injected = set()
        self.now = 0

    @property
    def header(self):
        return self._header

    def render(self, task=None):
        if not self._lines:
            self.last_injected = set()
            return ""
        self.last_injected = {fid for fid, _ in self._lines}
        return self._header + "\n" + "\n".join(f"- {l}" for _, l in self._lines) + "\n"

    def injectable_items(self):
        return list(self._lines)

    def injected_ids(self):
        return sorted(self.last_injected)

    def seed_injected(self, ids):
        self.last_injected = {i for i in ids or () if i in {fid for fid, _ in self._lines}}

    def update(self, *a, **k):
        pass

    def save(self, root):
        pass

    def debug_row(self):
        return {}


ENV_HEAD = "# environment facts learned from earlier sessions in this repository"
MANUAL_HEAD = "# repo operating manual (widget) — learned from earlier sessions in this repository"


def _composed(env_lines, manual_lines, **caps):
    return ComposedDistiller(_Layer(ENV_HEAD, env_lines), _Layer(MANUAL_HEAD, manual_lines), **caps)


# ---- the budget covers the block, not a layer -------------------------------------------
def test_the_budget_caps_the_block_over_both_layers():
    stage = _composed([("env-a", "environment fact A")],
                      [(f"m{i}", f"manual fact number {i} with some length to it") for i in range(4)],
                      max_facts=3)
    block = stage.render()
    lines = [l for l in block.splitlines() if l.startswith("- ")]
    assert len(lines) == 3                       # the env fact, then two manual facts
    assert lines[0].endswith("environment fact A")
    assert stage.injected_ids() == ["env-a", "m0", "m1"]


def test_the_token_budget_is_shared_by_both_layers():
    stage = _composed([("env-a", "environment fact A")],
                      [(f"m{i}", "manual fact " + "x" * 40) for i in range(3)],
                      max_facts=8, max_tokens=60)   # 240 characters, header included
    block = stage.render()
    assert block and len(block) <= 60 * 4
    assert len([l for l in block.splitlines() if l.startswith("- ")]) == 3   # env + two manual
    assert stage.injected_ids() == ["env-a", "m0", "m1"]


def test_the_block_carries_one_header_and_the_manual_alone_keeps_its_own():
    both = _composed([("env-a", "environment fact A")], [("m0", "manual fact")], max_facts=8)
    assert both.render().count("#") == 1
    env_frame = both.render().splitlines()[0]
    assert env_frame == ENV_HEAD
    manual = ComposedDistiller(None, _Layer(MANUAL_HEAD, [("m0", "manual fact")]), max_facts=8)
    assert manual.render().splitlines()[0] == MANUAL_HEAD


def test_a_line_that_does_not_fit_is_left_out_whole_and_the_next_one_is_tried():
    stage = _composed([], [("short", "short fact"), ("long", "y" * 300), ("m2", "another fact")],
                      max_facts=8, max_tokens=60)
    ids = stage.injected_ids() if stage.render() else []
    assert "long" not in ids                      # skipped, never cut
    assert "m2" in ids                            # and the next candidate still gets a turn


def test_nothing_fits_means_no_block_and_no_ids():
    stage = _composed([], [("long", "z" * 400)], max_facts=4, max_tokens=60)
    assert stage.render() == ""
    assert stage.injected_ids() == []
    assert stage.dist.last_injected == set()


def test_the_environment_layer_budgets_itself_and_keeps_its_own_ids():
    """Alone, the environment layer renders and reports as it always did: it budgets
    itself, and re-budgeting its block here would detach its ids from its lines."""
    env = _Layer(ENV_HEAD, [("e0", "a"), ("e1", "b")])
    stage = ComposedDistiller(env, None, max_facts=2)
    assert stage.render() == env.render()
    assert stage.injected_ids() == ["e0", "e1"]


def test_the_configured_caps_reach_the_environment_layer():
    from tokeneconomizer.config import InjectionConfig
    from tokeneconomizer.microskills import PrefixStage
    cfg = InjectionConfig(enabled=True, profile="envfacts", max_facts=2, max_tokens=40)
    stage = PrefixStage(cfg, "acme/widget", _tmp_root(), fresh=True)
    assert (stage.distiller.env.max_facts, stage.distiller.env.max_tokens) == (2, 40)
    assert stage.distiller.max_facts == 2 and stage.distiller.max_tokens == 40


def test_no_configured_cap_falls_back_to_the_environment_layers_own_defaults():
    from tokeneconomizer.config import InjectionConfig
    from tokeneconomizer.microskills import PrefixStage
    from tokeneconomizer.microskills import envfacts
    cfg = InjectionConfig(enabled=True, profile="envfacts+distiller")   # 0: keep the defaults
    stage = PrefixStage(cfg, "acme/widget", _tmp_root(), fresh=True)
    assert (stage.distiller.max_facts, stage.distiller.max_tokens) == (
        envfacts.MAX_FACTS, envfacts.MAX_TOKENS)
    assert stage.distiller.debug_row()["_profile"] == "envfacts+distiller"


def _tmp_root():
    import tempfile
    return tempfile.mkdtemp(prefix="te-block-")


# ---- the credit: a fact the session was given and whose waste did not occur --------------
def _active_fact(fid, line):
    """A native fact at 4/4 on its firing gate: injectable, and tracked per task."""
    fact = Fact({"id": fid, "claim": fid, "injection": line,
                 "detector": {"scope": "ran_tests", "fired": "command_failed"}})
    fact.life.state = "ACTIVE"
    fact.life.fire_num, fact.life.fire_den = 4, 4
    return fact


def _quiet_digest():
    """Tests ran, nothing failed: the waste the fact prevents did not occur."""
    return {"features": {}, "test_invocations": 1, "failed_commands": [],
            "_cmd_blob": "python -m pytest -q", "_out_blob": "3 passed"}


def test_a_fact_the_session_was_given_is_credited_when_its_waste_does_not_occur():
    fact = _active_fact("use-pytest", "run tests with python -m pytest")
    verdict, fired, exercised = fact.observe(7, _quiet_digest(), set(), injected=True)
    assert (fired, exercised) == (True, True)
    assert (fact.life.fire_num, fact.life.fire_den) == (5, 5)


def test_a_fact_the_session_was_not_given_keeps_the_plain_reading():
    fact = _active_fact("use-pytest", "run tests with python -m pytest")
    fact.observe(7, _quiet_digest(), set(), injected=False)
    assert (fact.life.fire_num, fact.life.fire_den) == (4, 5)


def test_the_fold_asks_the_block_which_facts_the_session_was_given(tmp_path):
    d = Distiller("acme/widget")
    d.facts = {"use-pytest": _active_fact("use-pytest", "run tests with python -m pytest")}
    d.seed_injected(["use-pytest"])
    assert d.injected_ids() == ["use-pytest"]
    d._observe_fact(d.facts["use-pytest"], 3, _quiet_digest(), set())
    assert d.facts["use-pytest"].life.fire_num == 5


def test_an_envfact_credited_through_the_composition_reaches_its_own_layer(tmp_path):
    """The composed block seeds both layers, so each credits only what it carries."""
    env = EnvFactsDistiller("acme/widget")
    stage = ComposedDistiller(env, None, max_facts=4, max_tokens=150)
    stage.seed_injected(["not-mine"])
    assert env.last_injected == set()
