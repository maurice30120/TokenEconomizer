"""The selected delivery points govern real hooks and keep one context allowance."""
import json

import pytest

from tokeneconomizer.knowledge.stage import Knowledge, workspace_id
from tokeneconomizer.plugin.config import load_config, unset_config, write_config
from tokeneconomizer.plugin.context import LiveContext
from tokeneconomizer.plugin.hosts import ClaudeCode, Copilot, Pi
from tests.test_knowledge_read import _prompt, _read
from tests.test_knowledge_workflow import learn_knowledge
from tests.test_live_hooks import call, env, repo  # noqa: F401


@pytest.fixture
def cards(tmp_path, env, repo, monkeypatch):
    names = ["a.txt", "b.txt", "c.txt", "d.txt"]
    enabled = learn_knowledge(
        tmp_path, env, repo, monkeypatch, dict.fromkeys(names, "observed\n"),
        [{"id": name[0], "claim": f"card for {name}", "source": name} for name in names])
    enabled.update(TE_KNOWLEDGE_MAX_CARDS="3", TE_KNOWLEDGE_MAX_TOKENS="1000",
                   TE_KNOWLEDGE_STARTUP_SHARE="0.5")
    src = LiveContext.build(ClaudeCode(), repo, enabled)
    stage = Knowledge.load(workspace_id(src.repo.label, repo), src.mech_dir)
    for host in (Pi(), Copilot()):
        stage.save(LiveContext.build(host, repo, enabled).mech_dir)
    return enabled


def start(settings, repo, host, source="startup", sid="mode"):
    return json.dumps(call(settings, {"hook_event_name": "SessionStart", "source": source,
                                     "session_id": sid, "cwd": repo}, host))


@pytest.mark.parametrize("host,tool", [("pi", "read"), ("copilot", "view")])
@pytest.mark.parametrize("mode,initial,later", [
    ("startup", 3, 0), ("tools", 0, 3), ("both", 1, 2)])
def test_modes_choose_delivery_points_and_share_one_allowance(cards, repo, host, tool,
                                                             mode, initial, later):
    settings = dict(cards, TE_KNOWLEDGE_INJECTION=mode)
    startup = start(settings, repo, host)
    assert startup.count("card for") == initial
    assert "card for" not in json.dumps(_prompt(settings, repo, "mode", "a.txt", host))
    outputs = [json.dumps(_read(settings, repo, "mode", f"{name}.txt", host=host,
                               name=tool, key="path", call_id=name)) for name in "abcd"]
    assert sum(out.count("card for") for out in outputs) == later
    for name in "abcd":
        assert (startup + "".join(outputs)).count(f"card for {name}.txt") <= 1
    assert "card for" not in json.dumps(_read(settings, repo, "mode", "a.txt", host=host,
                                              name=tool, key="path", call_id="again"))
    resumed = start(settings, repo, host, source="resume")
    assert resumed.count("card for") == (initial if host == "copilot" else 0)


@pytest.mark.parametrize("mode", ["startup", "tools", "both"])
def test_legacy_prompt_delivery_only_remains_in_both_mode(cards, repo, mode):
    settings = dict(cards, TE_KNOWLEDGE_INJECTION=mode)
    assert "card for" not in start(settings, repo, "claude")
    prompt = json.dumps(_prompt(settings, repo, "mode", "a.txt"))
    assert ("card for a.txt" in prompt) == (mode == "both")
    tool = json.dumps(_read(settings, repo, "mode", "b.txt"))
    assert ("card for b.txt" in tool) == (mode in ("tools", "both"))


@pytest.mark.parametrize("mode", ["startup", "tools", "both"])
@pytest.mark.parametrize("disabled", [{"TE_KNOWLEDGE": "off"}, {"TE_SHADOW": "on"}])
def test_disabled_and_shadow_suppress_all_selected_points(cards, repo, mode, disabled):
    settings = dict(cards, TE_KNOWLEDGE_INJECTION=mode, **disabled)
    assert "card for" not in start(settings, repo, "pi")
    assert "card for" not in json.dumps(_read(settings, repo, "mode", "a.txt", host="pi",
                                              name="read", key="path"))
    assert "card for" not in json.dumps(_prompt(settings, repo, "mode", "a.txt"))


def test_startup_mode_ignores_zero_startup_share_and_still_blocks_tools(cards, repo):
    settings = dict(cards, TE_KNOWLEDGE_INJECTION="startup", TE_KNOWLEDGE_STARTUP_SHARE="0")
    assert start(settings, repo, "pi").count("card for") == 3
    # No startup happened for this session, so capacity is available but tools stay disabled.
    assert "card for" not in json.dumps(_read(settings, repo, "no-start", "d.txt", host="pi",
                                              name="read", key="path"))


def test_switching_to_tools_does_not_restore_copilot_startup_cards(cards, repo):
    settings = dict(cards, TE_KNOWLEDGE_INJECTION="both")
    assert start(settings, repo, "copilot").count("card for") == 1
    settings["TE_KNOWLEDGE_INJECTION"] = "tools"
    assert "card for" not in start(settings, repo, "copilot", source="resume")
    # Copilot rebuilt context without the startup card, freeing its allowance.
    outputs = [json.dumps(_read(settings, repo, "mode", f"{name}.txt", host="copilot",
                               name="view", key="path")) for name in "abcd"]
    assert sum(out.count("card for") for out in outputs) == 3


def test_mode_configuration_validates_persists_overrides_and_unsets(tmp_path):
    path = str(tmp_path / "config.json")
    assert load_config(str(tmp_path), env={}).knowledge_injection == "both"
    for mode in ("startup", "tools", "both"):
        write_config(path, {"knowledge_injection": mode})
        assert load_config(str(tmp_path), env={}).knowledge_injection == mode
    with pytest.raises(ValueError, match="knowledge_injection"):
        write_config(path, {"knowledge_injection": "invalid"})
    assert load_config(str(tmp_path), env={}).knowledge_injection == "both"
    assert load_config(str(tmp_path), env={
        "TE_KNOWLEDGE_INJECTION": "tools"}).knowledge_injection == "tools"
    write_config(path, {"knowledge_injection": "startup"})
    unset_config(path, ["knowledge_injection"])
    assert load_config(str(tmp_path), env={}).knowledge_injection == "both"
