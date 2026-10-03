"""The models on this stick: what is installed, what a typed name means, which
one to open with, and which smaller one to fall back to.

Names are forgiving because people type them: "gemma3" finds gemma3:4b when
it is the only Gemma 3 installed, and "fast" / "max" (from sticks set up
before 0.4) mean the smallest and the largest installed model.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import catalog
from .ollama import OllamaClient, OllamaError


@dataclass
class Installed:
    name: str           # full tag, e.g. qwen3.5:4b
    size_gb: float
    family: str = ""
    params: str = ""    # e.g. "4.0B"

    @property
    def label(self) -> str:
        entry = catalog.find(self.name)
        return entry.name if entry else self.name


class ModelManager:
    def __init__(self, cfg, client: OllamaClient | None = None):
        self.cfg = cfg
        self.client = client or OllamaClient(cfg.ollama_host)
        self._installed: list[Installed] | None = None

    # ---- what is here ------------------------------------------------------------
    def installed(self, refresh: bool = False) -> list[Installed]:
        """Chat models on the stick, smallest first. Embedding models (which
        cannot chat) are left out. Empty when the server is unreachable."""
        if self._installed is None or refresh:
            try:
                raw = self.client.models()
            except OllamaError:
                raw = []
            out = []
            for m in raw:
                name = m.get("name") or m.get("model") or ""
                details = m.get("details") or {}
                fams = " ".join(details.get("families") or [details.get("family") or ""]).lower()
                if not name or "bert" in fams or "embed" in name.lower():
                    continue
                out.append(Installed(name, (m.get("size") or 0) / 1e9,
                                     details.get("family", ""), details.get("parameter_size", "")))
            self._installed = sorted(out, key=lambda i: (i.size_gb, i.name))
        return self._installed

    def names(self) -> list[str]:
        return [m.name for m in self.installed()]

    def get(self, name: str) -> Installed | None:
        return next((m for m in self.installed() if m.name == name), None)

    # ---- names -----------------------------------------------------------------------
    def resolve(self, query: str) -> str | None:
        """A typed name to an installed tag, or None if nothing (or more than
        one thing) matches."""
        q = (query or "").strip().lower()
        names = self.names()
        if not q or not names:
            return None
        if q in ("fast", "small", "smallest", "haiku"):
            return self._legacy(self.cfg.legacy_fast) or names[0]
        if q in ("max", "big", "largest", "opus", "sonnet"):
            return self._legacy(self.cfg.legacy_max) or names[-1]
        lowered = {n.lower(): n for n in names}
        for cand in (q, q + ":latest"):
            if cand in lowered:
                return lowered[cand]
        entry = catalog.find(q)
        if entry and entry.tag.lower() in lowered:
            return lowered[entry.tag.lower()]
        for test in (lambda n: n.startswith(q), lambda n: q in n):
            hits = [n for n in names if test(n.lower())]
            if len(hits) == 1:
                return hits[0]
        return None

    def _legacy(self, tag: str) -> str | None:
        return tag if tag and tag in self.names() else None

    def default(self) -> str:
        """The model to open with: the configured one if it is here, else the
        best installed one by the catalog's ranking, else the largest."""
        names = self.names()
        if self.cfg.model:
            hit = self.resolve(self.cfg.model)
            if hit:
                return hit
            if not names:
                return self.cfg.model
        if not names:
            return ""
        ranked = sorted(self.installed(), key=lambda m: (catalog.rank_of(m.name), m.size_gb))
        return ranked[-1].name

    # ---- switching ---------------------------------------------------------------------
    def next_after(self, current: str) -> str:
        """Ctrl-T order: smallest to largest, then round again."""
        names = self.names()
        if not names:
            return current
        if current not in names:
            return names[0]
        return names[(names.index(current) + 1) % len(names)]

    def smaller_than(self, current: str) -> list[str]:
        """Installed models smaller than `current`, largest first: the order
        to try when `current` will not load on this computer."""
        cur = self.get(current)
        if cur is None:
            return []
        return [m.name for m in reversed(self.installed()) if m.size_gb < cur.size_gb]

    def capabilities(self, name: str) -> set[str]:
        """What the server says the model can do. Falls back to the catalog
        when the server is too old to say."""
        caps = self.client.capabilities(name)
        if caps:
            return caps
        entry = catalog.find(name)
        if not entry:
            return {"completion"}
        caps = {"completion"}
        if entry.tools:
            caps.add("tools")
        if entry.vision:
            caps.add("vision")
        if entry.thinking:
            caps.add("thinking")
        return caps
