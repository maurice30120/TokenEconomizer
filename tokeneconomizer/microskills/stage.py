"""`PrefixStage`: the micro-skill lifecycle hook -- render before a session, learn after it.

It builds the distiller the profile names -- the LLM-free environment facts (`envfacts`), the
paid proposer (`distiller`), or both (`envfacts+distiller`, the free layer first and its claims
handed to the proposer as already stated) -- renders its block for the next session, and folds
each finished session back in, reporting the paid proposer's cost for that session.
"""
import os

from ..names import repo_filename
from ..stage import Stage
from . import distiller as _distiller
from .distiller import Distiller


# ---- composition: the free environment layer under the paid manual -------------------
class ComposedDistiller:
    """`envfacts` first, the paid manual on top, driven as one distiller under one budget.

    The block is what the agent receives, so the caps `config` documents apply to the block
    and not to a layer: the environment layer renders first within the same allowance, the
    manual fills what is left one line at a time -- a line that does not fit is left out
    whole, and the next one is still tried. Both layers say which facts made the block, so
    the fold can credit the sessions those facts were given. Either layer may be absent:
    `envfacts` alone, or the manual alone, runs through this same path and budget. Each
    layer folds every finished task and persists in its own state dir. Overhead is the
    proposer's alone -- the environment layer is LLM-free by construction."""
    def __init__(self, env, dist, max_facts=None, max_tokens=None):
        self.env, self.dist = env, dist
        self.max_facts = max_facts
        self.max_tokens = max_tokens
        self.last_injected = set()

    @property
    def opt_tokens(self):
        return self.dist.opt_tokens if self.dist is not None else 0.0

    @property
    def now(self):
        layer = self.dist if self.dist is not None else self.env
        return layer.now if layer is not None else 0

    def _fits(self, head, body):
        """Whether the block `head` + `body` stays inside both caps. A token is counted as
        four characters, the same estimate the environment layer budgets with."""
        if self.max_facts and len(body) > self.max_facts:
            return False
        if self.max_tokens is not None:
            text = head + "\n" + "\n".join(f"- {line}" for line in body) + "\n"
            if len(text) > self.max_tokens * 4:
                return False
        return True

    def render(self, task=None):
        if self.dist is None:
            # The environment layer budgets itself (`EnvFactsDistiller._select`), and its own
            # ids must stay attached to the lines it chose: nothing to re-budget here.
            block = self.env.render(task) if self.env is not None else ""
            self.last_injected = set(self.env.injected_ids()) if block and self.env else set()
            return block
        env_block = self.env.render(task) if self.env is not None else ""
        body = [line[2:] for line in env_block.splitlines() if line.startswith("- ")]
        ids = set(self.env.injected_ids()) if body and self.env is not None else set()
        head = env_block.splitlines()[0] if body else self.dist.header
        kept = []
        for fid, line in self.dist.injectable_items():
            if self._fits(head, body + [line]):
                body.append(line)
                kept.append(fid)
        self.dist.seed_injected(kept)
        ids |= set(kept)
        self.last_injected = ids
        if not body:
            return ""
        return head + "\n" + "\n".join(f"- {line}" for line in body) + "\n"

    def injected_ids(self):
        """The ids of the facts the last `render` chose, both layers: what the session gets."""
        return sorted(self.last_injected)

    def seed_injected(self, ids):
        ids = list(ids or ())
        if self.env is not None:
            self.env.seed_injected(ids)
        if self.dist is not None:
            self.dist.seed_injected(ids)
        self.last_injected = set(ids)

    def update(self, transcript_path, iid="", resolved=None, edited=None):
        if self.env is not None:
            self.env.update(transcript_path, iid=iid, resolved=resolved, edited=edited)
        if self.dist is not None:
            self.dist.update(transcript_path, iid=iid, resolved=resolved, edited=edited)

    def save(self, root):
        if self.env is not None:
            self.env.save(root)
        if self.dist is not None:
            self.dist.save(root)

    def debug_row(self):
        row = dict(self.dist.debug_row()) if self.dist is not None else {}
        if self.env is not None:
            row.update(self.env.debug_row())
            row["_profile"] = ("envfacts+distiller" if self.dist is not None else "envfacts")
        elif self.dist is not None:
            row["_profile"] = "distiller"
        return row


# ---- lifecycle stage -------------------------------------------------------
class PrefixStage(Stage):
    """Injection lifecycle hook: render the manual before a task, fold the finished
    task back into the distiller after it, and report the paid proposer's per-task
    token delta for the amortized ledger."""
    name = "prefix"

    def __init__(self, cfg, repo, results_root, fresh,
                 runner=None, optimizer_model="agent", adapter=None, agent=None,
                 shared_propose=None):
        self.results_root = results_root
        self.adapter = adapter
        self.agent = agent
        # The Distiller is the single source of truth for the proposer cadence: rebind
        # the module global that update()'s gate reads (process-local, idempotent).
        pe = int(getattr(cfg, "propose_every", 0) or 0)
        if pe > 0:
            _distiller.PROPOSE_EVERY = pe
        profile = getattr(cfg, "profile", "distiller") or "distiller"
        # The environment-fact layer reads intents through a domain vocabulary; the adapter
        # supplies it when it has one (SWE-bench: Python/git; Web-Bench: Node/npm).
        vocab = adapter.env_vocabulary() if hasattr(adapter, "env_vocabulary") else None
        # The caps apply to the block the agent receives, whatever layers compose it. 0 keeps
        # the environment layer's own defaults, so the block's fallback is the same one.
        from .envfacts import MAX_FACTS, MAX_TOKENS
        caps = {"max_facts": getattr(cfg, "max_facts", 0) or MAX_FACTS,
                "max_tokens": getattr(cfg, "max_tokens", 0) or MAX_TOKENS}
        env = None
        if "envfacts" in profile:
            from .envfacts import EnvFactsDistiller
            env = (EnvFactsDistiller(repo, vocab=vocab, **caps) if fresh
                   else EnvFactsDistiller.load(repo, results_root, vocab=vocab, **caps))
        if profile == "envfacts":
            # LLM-free environment facts alone. Same render/update/save interface, no
            # runner, opt_tokens stays 0 -- the ledger sees no overhead.
            self.reason = "envfacts"
            self.distiller = ComposedDistiller(env, None, **caps)
        else:
            # The paid proposer; with `envfacts+distiller` it is told which claims the free
            # layer already injects, so it authors only facts beyond them.
            external = env.injectable_claims if env is not None else None
            dist = (Distiller(repo, runner=runner, model=optimizer_model,
                              external_facts=external, vocab=vocab) if fresh
                    else Distiller.load(repo, results_root, runner=runner,
                                        model=optimizer_model, external_facts=external,
                                        vocab=vocab))
            dist.shared_propose = shared_propose
            if env is not None:
                self.reason = "envfacts+manual-distill"
                self.distiller = ComposedDistiller(env, dist, **caps)
            else:
                self.reason = "manual-distill"
                self.distiller = ComposedDistiller(None, dist, **caps)

    def render(self, task=None):
        """The firing-gated repo manual injected into the NEXT task's prefix."""
        return self.distiller.render(task=task) if self.distiller else ""

    def injected_ids(self):
        """The environment facts the last `render` chose, [] without that layer."""
        get = getattr(self.distiller, "injected_ids", None)
        return get() if get else []

    def after_task(self, task, row, run_dir_path, srow):
        """Fold the finished task into the fact lifecycle; return (opt_tokens, reason).
        The paid proposer accrues cumulatively on distiller.opt_tokens; capture THIS
        task's delta for the per-task ledger (same effective-token basis). A task that names
        `injected_ids` says which environment facts it was given (see `seed_injected`)."""
        transcript = os.path.join(run_dir_path, "transcript.jsonl")
        seed = getattr(self.distiller, "seed_injected", None)
        if seed and task.get("injected_ids") is not None:
            seed(task["injected_ids"])
        before = self.distiller.opt_tokens
        self.distiller.update(transcript, iid=task["instance_id"],
                              resolved=srow.get("resolved"))
        self.distiller.save(self.results_root)
        opt_tokens = self.distiller.opt_tokens - before
        srow["manual_facts"] = self.distiller.debug_row()
        return opt_tokens, self.reason


# ---- forgetting a fact by hand ---------------------------------------------
def _saved_layers(repo, root, vocab=None):
    """The distillers with state saved under `root`, loaded: the environment layer first."""
    from . import envfacts
    from ..knowledge.stage import Knowledge
    out = []
    for cls, sub in ((envfacts.EnvFactsDistiller, envfacts.STATE_SUBDIR),
                     (Distiller, _distiller.STATE_SUBDIR)):
        if os.path.exists(os.path.join(root, sub, repo_filename(repo) + ".json")):
            out.append(cls.load(repo, root, vocab=vocab))
    if os.path.exists(os.path.join(root, "knowledge_state", repo_filename(repo) + ".json")):
        out.append(Knowledge.load(repo, root, vocab=vocab))
    return out


def forget_facts(repo, root, ids, vocab=None, undo=False):
    """Forget the facts `ids` (or, with `undo`, bring them back) in whichever saved layer holds
    each, and save the layers that changed. A forgotten fact is no longer rendered, and is not
    learned again under its id. Returns [(id, changed, claim)] in the order given. When an id
    is unknown to every layer nothing is changed, and KeyError carries the unknown ids."""
    layers = _saved_layers(repo, root, vocab)
    owner = {}
    for layer in layers:
        for fid in layer.known_ids():
            owner.setdefault(fid, layer)
    unknown = [fid for fid in ids if fid not in owner]
    if unknown:
        raise KeyError(unknown)
    out, changed = [], []
    for fid in dict.fromkeys(ids):
        layer = owner[fid]
        did = layer.unforget(fid) if undo else layer.forget(fid)
        if did and layer not in changed:
            changed.append(layer)
        fact = layer.facts.get(fid)
        claim = (layer._claim_of(fact) if fact is not None
                 else layer.forgotten.get(fid, {}).get("claim", ""))
        out.append((fid, did, claim))
    for layer in changed:
        layer.save(root)
    return out


def forgotten_facts(repo, root, vocab=None):
    """{id: the claim it made} for every forgotten fact saved under `root`."""
    out = {}
    for layer in _saved_layers(repo, root, vocab):
        for fid, rec in layer.forgotten.items():
            out.setdefault(fid, rec.get("claim", ""))
    return out
