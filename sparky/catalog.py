"""A curated list of open-weight models that run from a stick on a normal
computer, and a recommender that picks by purpose rather than by name.

Sizes are the Ollama downloads (default quantisation) checked against the
registry in October 2026. "active_b" is the billions of parameters used per
token: it decides speed on a CPU far more than the total size does, which is
why mixture-of-experts models (30B total, 3B active) feel quicker than dense
14B ones.

To add a model: add an Entry, then add its tag to the PICKS list of each
purpose it is good for, in order of preference. Check the tag exists at
https://ollama.com/library and that it runs on a laptop without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass

APACHE = "Apache 2.0"
GEMMA = "Gemma Terms of Use"


@dataclass(frozen=True)
class Entry:
    tag: str
    name: str
    maker: str
    size_gb: float          # download, and roughly the space on the stick
    params_b: float         # total parameters, billions
    active_b: float         # parameters used per token, billions
    licence: str
    note: str
    vision: bool = False
    tools: bool = False
    thinking: bool = False

    @property
    def ram_gb(self) -> float:
        """Memory to run it with a useful context window: the weights plus
        room for the conversation and the server itself."""
        return round(self.size_gb + (1.5 if self.size_gb < 10 else 2.5), 1)

    @property
    def speed(self) -> str:
        """How it feels on a typical laptop CPU (Apple Silicon is quicker)."""
        if self.active_b <= 5:
            return "quick"
        if self.active_b <= 10:
            return "steady"
        return "slow"


E = Entry
ENTRIES: list[Entry] = [
    # ---- small: any laptop, 8 GB of memory or less ----
    E("qwen3.5:0.8b", "Qwen3.5 0.8B", "Alibaba Qwen", 1.0, 0.9, 0.9, APACHE,
      "The smallest useful model; fine for short questions on old computers.", True, True, True),
    E("gemma3:1b", "Gemma 3 1B", "Google", 0.8, 1.0, 1.0, GEMMA,
      "Tiny and quick for simple writing and chat."),
    E("lfm2.5-thinking:1.2b", "LFM2.5 1.2B Thinking", "Liquid AI", 0.7, 1.2, 1.2, "LFM Open License 1.0",
      "Reasons step by step in under a gigabyte.", False, True, True),
    E("qwen2.5-coder:1.5b", "Qwen2.5 Coder 1.5B", "Alibaba Qwen", 1.0, 1.5, 1.5, APACHE,
      "Small code helper for explaining and short snippets.", False, True),
    E("deepseek-r1:1.5b", "DeepSeek-R1 1.5B", "DeepSeek", 1.1, 1.5, 1.5, "MIT",
      "Tiny reasoning model; shows its working.", False, True, True),
    E("moondream:1.8b", "Moondream 2", "Vikhyat Korrapati", 1.7, 1.8, 1.8, APACHE,
      "Describes photos and screenshots on very little memory.", True),
    E("qwen3.5:2b", "Qwen3.5 2B", "Alibaba Qwen", 2.7, 2.3, 2.3, APACHE,
      "Small all-rounder that also reads images.", True, True, True),
    E("qwen3-vl:2b", "Qwen3-VL 2B", "Alibaba Qwen", 1.9, 2.1, 2.1, APACHE,
      "Small model built for images, documents and screenshots.", True, True, True),
    E("llama3.2:3b", "Llama 3.2 3B", "Meta", 2.0, 3.2, 3.2, "Llama 3.2 Community License",
      "Plain, reliable chat and writing on small machines.", False, True),
    E("phi4-mini:3.8b", "Phi-4 mini", "Microsoft", 2.5, 3.8, 3.8, "MIT",
      "Good at maths and reasoning for its size.", False, True),
    E("granite4.1:3b", "Granite 4.1 3B", "IBM", 2.1, 3.0, 3.0, APACHE,
      "Built for answering from documents.", False, True),
    E("ministral-3:3b", "Ministral 3 3B", "Mistral AI", 3.0, 3.0, 3.0, APACHE,
      "Small, quick and multilingual, reads images.", True, True),
    E("nemotron-3-nano:4b", "Nemotron 3 Nano 4B", "NVIDIA", 2.8, 4.0, 4.0, "NVIDIA Open Model License",
      "Small reasoning model with a very long context.", False, True, True),
    E("gemma3:4b", "Gemma 3 4B", "Google", 3.3, 4.3, 4.3, GEMMA,
      "Natural writing in many languages; reads images.", True),
    E("qwen3-vl:4b", "Qwen3-VL 4B", "Alibaba Qwen", 3.3, 4.4, 4.4, APACHE,
      "Reads screenshots, photos and scanned pages well.", True, True, True),
    E("translategemma:4b", "TranslateGemma 4B", "Google", 3.3, 4.3, 4.3, GEMMA,
      "Translation between 55 languages, including text in images.", True),
    E("qwen3.5:4b", "Qwen3.5 4B", "Alibaba Qwen", 3.4, 4.7, 4.7, APACHE,
      "The best all-rounder for 8 GB laptops: chat, code, images, 200+ languages.", True, True, True),

    # ---- medium: 16 GB of memory ----
    E("qwen2.5-coder:7b", "Qwen2.5 Coder 7B", "Alibaba Qwen", 4.7, 7.6, 7.6, APACHE,
      "Solid code completion and explanation.", False, True),
    E("llama3.1:8b", "Llama 3.1 8B", "Meta", 4.9, 8.0, 8.0, "Llama 3.1 Community License",
      "A dependable general model.", False, True),
    E("lfm2.5:8b", "LFM2.5 8B", "Liquid AI", 5.2, 8.3, 1.5, "LFM Open License 1.0",
      "Mixture of experts with about 1.5B active: very quick for its size.", False, True, True),
    E("deepseek-r1:8b", "DeepSeek-R1 8B", "DeepSeek", 5.2, 8.2, 8.2, "MIT",
      "Thinks before answering; good for maths and logic.", False, True, True),
    E("granite4.1:8b", "Granite 4.1 8B", "IBM", 5.3, 8.0, 8.0, APACHE,
      "Careful answers from your own documents.", False, True),
    E("ministral-3:8b", "Ministral 3 8B", "Mistral AI", 6.0, 8.0, 8.0, APACHE,
      "Multilingual chat that reads images.", True, True),
    E("qwen3-vl:8b", "Qwen3-VL 8B", "Alibaba Qwen", 6.1, 8.8, 8.8, APACHE,
      "Strong at charts, forms, handwriting and screenshots.", True, True, True),
    E("qwen3.5:9b", "Qwen3.5 9B", "Alibaba Qwen", 6.6, 9.7, 9.7, APACHE,
      "The best all-rounder for 16 GB: chat, code, documents, images.", True, True, True),
    E("gemma4:12b", "Gemma 4 12B", "Google", 8.0, 11.9, 11.9, APACHE,
      "Excellent writing and translation, reads images.", True, True, True),
    E("gemma3:12b", "Gemma 3 12B", "Google", 8.1, 12.2, 12.2, GEMMA,
      "Warm, natural writing in many languages.", True),
    E("translategemma:12b", "TranslateGemma 12B", "Google", 8.1, 12.2, 12.2, GEMMA,
      "Higher quality translation, including text in images.", True),
    E("qwen2.5-coder:14b", "Qwen2.5 Coder 14B", "Alibaba Qwen", 9.0, 14.8, 14.8, APACHE,
      "Stronger code model for 16 GB machines; slower.", False, True),
    E("deepseek-r1:14b", "DeepSeek-R1 14B", "DeepSeek", 9.0, 14.8, 14.8, "MIT",
      "Deeper reasoning; slow on a CPU.", False, True, True),
    E("phi4:14b", "Phi-4 14B", "Microsoft", 9.1, 14.7, 14.7, "MIT",
      "Careful reasoning and writing.", False),

    # ---- large: 32 GB of memory or more ----
    E("gpt-oss:20b", "gpt-oss 20B", "OpenAI", 14.0, 21.0, 3.6, APACHE,
      "Strong reasoning and tool use; mixture of experts, so quick for its size.", False, True, True),
    E("gemma4:26b", "Gemma 4 26B", "Google", 18.0, 25.2, 4.0, APACHE,
      "Top writing quality that still runs quickly (4B active); reads images.", True, True, True),
    E("qwen3-coder:30b", "Qwen3 Coder 30B", "Alibaba Qwen", 19.0, 30.5, 3.3, APACHE,
      "The best coding agent that runs on a laptop CPU (3.3B active).", False, True),
    E("glm-4.7-flash", "GLM-4.7 Flash", "Z.ai", 19.0, 29.9, 3.0, "MIT",
      "Strong coder and reasoner, mixture of experts.", False, True, True),
    E("qwen3.6:35b", "Qwen3.6 35B", "Alibaba Qwen", 23.0, 35.5, 3.0, APACHE,
      "The strongest all-rounder that fits a stick: agentic coding, images, reasoning.",
      True, True, True),
    # dense large models: excellent, but slow without a GPU, so never auto-picked
    E("devstral-small-2:24b", "Devstral Small 2", "Mistral AI", 15.0, 24.0, 24.0, APACHE,
      "Coding agent for big codebases; needs a fast machine.", True, True),
    E("qwen3.8:27b", "Qwen3.8 27B", "Alibaba Qwen", 18.0, 27.0, 27.0, APACHE,
      "Newest Qwen; dense, so best on Apple Silicon or a GPU.", True, True, True),
    E("gemma4:31b", "Gemma 4 31B", "Google", 20.0, 30.7, 30.7, APACHE,
      "Largest Gemma 4; dense, so slow on a CPU.", True, True, True),
]

BY_TAG = {e.tag: e for e in ENTRIES}

PURPOSES: dict[str, tuple[str, str]] = {
    "everyday": ("Everyday questions", "Chat, explanations, ideas, quick help with anything"),
    "code": ("Coding", "Reads, writes and runs code in a project folder"),
    "write": ("Writing", "Emails, essays, summaries, rewording, feedback on drafts"),
    "study": ("My documents", "Answers from notes and files you put in the context folder"),
    "vision": ("Images", "Reads screenshots, photos, charts and scanned pages"),
    "translate": ("Translation", "Translating text between languages"),
    "reason": ("Reasoning", "Maths, logic and planning, worked through step by step"),
}

# Per purpose, best first. The recommender takes the first ones that fit.
PICKS: dict[str, list[str]] = {
    "everyday": ["qwen3.6:35b", "gemma4:26b", "gpt-oss:20b", "gemma4:12b", "qwen3.5:9b",
                 "lfm2.5:8b", "qwen3.5:4b", "gemma3:4b", "phi4-mini:3.8b", "llama3.2:3b",
                 "qwen3.5:2b", "qwen3.5:0.8b", "gemma3:1b"],
    "code": ["qwen3-coder:30b", "glm-4.7-flash", "gpt-oss:20b", "qwen3.5:9b", "qwen2.5-coder:7b",
             "qwen3.5:4b", "qwen2.5-coder:1.5b"],
    "write": ["gemma4:26b", "gemma4:12b", "gemma3:12b", "qwen3.5:9b", "gemma3:4b",
              "llama3.2:3b", "gemma3:1b"],
    "study": ["qwen3.6:35b", "gpt-oss:20b", "qwen3.5:9b", "granite4.1:8b", "qwen3.5:4b",
              "phi4-mini:3.8b", "granite4.1:3b", "qwen3.5:2b", "qwen3.5:0.8b"],
    "vision": ["qwen3.6:35b", "gemma4:26b", "qwen3-vl:8b", "gemma4:12b", "qwen3.5:9b",
               "qwen3-vl:4b", "qwen3.5:4b", "gemma3:4b", "qwen3-vl:2b", "moondream:1.8b"],
    "translate": ["gemma4:26b", "translategemma:12b", "gemma4:12b", "qwen3.5:9b",
                  "translategemma:4b", "qwen3.5:4b", "gemma3:4b", "gemma3:1b"],
    "reason": ["gpt-oss:20b", "qwen3.6:35b", "deepseek-r1:8b", "deepseek-r1:14b",
               "nemotron-3-nano:4b", "phi4-mini:3.8b", "qwen3.5:4b", "lfm2.5-thinking:1.2b",
               "deepseek-r1:1.5b"],
}


def find(name: str) -> Entry | None:
    """The catalog entry for a tag (":latest" and case are ignored)."""
    n = (name or "").strip().lower()
    if n.endswith(":latest"):
        n = n[: -len(":latest")]
    return BY_TAG.get(n)


def rank_of(name: str) -> int:
    """Higher is better: how early the model appears across the purpose lists.
    Used to choose the default among installed models."""
    best = 0
    for picks in PICKS.values():
        e = find(name)
        if e and e.tag in picks:
            best = max(best, len(picks) - picks.index(e.tag))
    return best


def usable_ram(total_ram_gb: float) -> float:
    """Memory a model can have on a computer with this much installed: the
    operating system and open apps keep the rest."""
    return total_ram_gb - max(2.5, total_ram_gb * 0.2)


def fits(entry: Entry, ram_gb: float, space_gb: float | None = None) -> bool:
    if ram_gb and entry.ram_gb > usable_ram(ram_gb):
        return False
    if space_gb is not None and entry.size_gb > space_gb:
        return False
    return True


def recommend(purpose: str, ram_gb: float, space_gb: float | None = None, n: int = 3) -> list[Entry]:
    """The best models for a purpose that fit this much memory and space."""
    picks = PICKS.get(purpose, PICKS["everyday"])
    return [BY_TAG[t] for t in picks if fits(BY_TAG[t], ram_gb, space_gb)][:n]


def plan(purposes: list[str], ram_gb: float, space_gb: float) -> list[Entry]:
    """One model per purpose (shared where one covers several), plus a small
    quick one for Ctrl-T when there is room, all within the space."""
    chosen: list[Entry] = []
    left = space_gb
    for p in purposes or ["everyday"]:
        options = recommend(p, ram_gb, left, n=3)
        # a model already chosen that is among this purpose's top two covers it
        if any(e in chosen for e in options[:2]):
            continue
        if options:
            chosen.append(options[0])
            left -= options[0].size_gb
    quick = next((e for e in recommend("everyday", min(ram_gb, 8) or 8, left, n=20)
                  if e.speed == "quick" and e.size_gb <= 3.5 and e not in chosen), None)
    if quick and chosen and chosen[0].size_gb > 6:
        chosen.append(quick)
    return chosen
