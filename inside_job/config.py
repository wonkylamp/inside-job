"""Load and validate the TOML game config into dataclasses."""

from __future__ import annotations

import copy
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CLUE_STRENGTHS = {"weak": 0.8, "normal": 0.6, "strong": 0.4}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# Keys allowed below zero (with their minimum); every other number must be >= 0.
_NEGATIVE_OK = {"max_thinking_tokens": -1}

# Heist codenames for anonymised games: short, distinct, single words, none of which is (or
# contains) a model family name.
CODENAMES = ("Ghost", "Viper", "Duke", "Sparrow", "Onyx", "Marlow", "Quill", "Sable", "Wren",
             "Fox", "Cipher", "Lark", "Bishop", "Juno", "Rook", "Ember", "Slate", "Moth",
             "Tinker", "Vesper")


class ConfigError(ValueError):
    pass


@dataclass
class GameConfig:
    num_moles: int = 2
    clues_per_round: int = 1
    clue_strength: str = "weak"
    clue_recipients: int = 3           # mean number of alive players dealt a clue a round; 0 = everyone
    clue_recipients_spread: int = 1    # the real number is drawn from recipients +/- spread
    max_rounds: int = 0
    job_size: int = 3
    job_size_small: int = 2
    clean_target: int = 3
    sabotage_target: int = 3
    whispers: bool = True
    whisper_pairs_max: int = 3
    whisper_exchanges: int = 2
    discussion_passes: int = 2
    finale_exchanges: int = 1
    pot: int = 100
    anonymise: bool = False
    # v0.4 candidate rules (docs/V04.md): off by default, scripted bots only for now.
    mole_score_target: int = 0         # 0 = off; > 0: moles win at blown jobs + crew voted out
    vote_nobody: bool = False          # the vote offers `nobody`; eject only on a strict majority
    forced_vote_after: int = 2         # with vote_nobody: after this many empty votes the next is forced
    team_approval: bool = False        # pre-job debate with approve / reject
    whisper_pairing: str = "chosen"    # "chosen" | "random" (the engine draws the pairs)
    clue_turn: bool = True             # false: clues are dealt but no clue-phase call is made
    endings: str = "classic"           # "classic" | "stakes"
    unique_clues: bool = False         # no two players dealt the same clue in one round

    def v04_dials(self) -> list[str]:
        """Names of the v0.4 dials that are away from their default (docs/V04.md)."""
        fields = type(self).__dataclass_fields__
        return [k for k in V04_DIALS if getattr(self, k) != fields[k].default]


V04_DIALS = ("mole_score_target", "vote_nobody", "forced_vote_after", "team_approval", "whisper_pairing",
             "clue_turn", "endings", "unique_clues")
WHISPER_PAIRINGS = ("chosen", "random")
ENDINGS = ("classic", "stakes")
NOBODY = "nobody"                      # the vote option for ejecting no one (vote_nobody)


@dataclass
class LimitsConfig:
    max_parallel_calls: int = 4
    call_timeout_s: float = 240
    retries: int = 2
    confessional_words: int = 70
    public_words: int = 60
    whisper_words: int = 50
    memory_words: int = 60
    word_grace: float = 0.15           # hard cap = ceil(limit * (1 + word_grace)); 0 = no grace
    max_thinking_tokens: int = 2000    # MAX_THINKING_TOKENS for every call; 0 = off; -1 = not set
    effort: str = "low"                # --effort <level>; "" = flag not passed


@dataclass
class NarratorConfig:
    model: str = "claude-haiku-4-5"
    recap_words: int = 100


@dataclass
class PlayerConfig:
    model: str
    name: str
    role: str | None = None   # fixed role ("mole" | "crew"), or None when roles are dealt


def is_openrouter_model(model_id: str) -> bool:
    """A model id with a "/" (`vendor/model`) is called through OpenRouter (docs/OPENROUTER.md);
    an id without one is a Claude model called through `claude -p`."""
    return "/" in model_id


# Default top of the output-limit escalation (docs/OPENROUTER.md): after an empty or cut-off reply
# with finish_reason "length", the next attempt of that turn asks for twice the previous limit, never
# above this. A starting limit above it is never lowered (no escalation for that model then).
DEFAULT_OUTPUT_CEILING = 16000
# The `reasoning.effort` values [openrouter.reasoning_effort_by_model] accepts (docs/OPENROUTER.md).
OPENROUTER_EFFORTS = ("none", "minimal", "low", "medium", "high")


@dataclass
class OpenRouterConfig:
    """The optional [openrouter] table (docs/OPENROUTER.md). Only used when the cast or narrator
    has an OpenRouter model id."""
    budget_usd: float | None = None    # billed spend in this process at which every paid request stops
    max_output_tokens: int = 6000      # per call, reasoning included (`max_tokens` on the wire)
    prices: dict = field(default_factory=dict)   # {"vendor/model": {"input": $/M, "output": $/M}}
    # {"vendor/model": tokens}: a model's own starting limit in place of max_output_tokens.
    max_output_tokens_by_model: dict = field(default_factory=dict)
    # The most any escalated attempt asks for. When the table does not set it, it is resolved at load
    # time to max(DEFAULT_OUTPUT_CEILING, every starting limit), so the logged value is the one used.
    max_output_tokens_ceiling: int = DEFAULT_OUTPUT_CEILING
    # {"vendor/model": effort}: this model's `reasoning.effort`, whatever [limits] says.
    reasoning_effort_by_model: dict = field(default_factory=dict)
    # {"vendor/model": [provider slugs]}: this model is sent only to these providers, in this order.
    providers_by_model: dict = field(default_factory=dict)

    def output_limit(self, model: str) -> int:
        """The starting `max_tokens` for this model's calls."""
        return self.max_output_tokens_by_model.get(model, self.max_output_tokens)

    def to_dict(self) -> dict:
        d = {"budget_usd": self.budget_usd, "max_output_tokens": self.max_output_tokens,
             "max_output_tokens_by_model": dict(self.max_output_tokens_by_model),
             "max_output_tokens_ceiling": self.max_output_tokens_ceiling,
             "prices": {m: dict(p) for m, p in self.prices.items()}}
        # Only when set, so the logged config of every config without them is unchanged.
        if self.reasoning_effort_by_model:
            d["reasoning_effort_by_model"] = dict(self.reasoning_effort_by_model)
        if self.providers_by_model:
            d["providers_by_model"] = {m: list(p) for m, p in self.providers_by_model.items()}
        return d


@dataclass
class Config:
    game: GameConfig
    limits: LimitsConfig
    narrator: NarratorConfig
    players: list[PlayerConfig]
    raw: dict = field(default_factory=dict)
    openrouter: OpenRouterConfig = field(default_factory=OpenRouterConfig)

    def openrouter_models(self) -> list[str]:
        """The distinct OpenRouter model ids in the cast and narrator, in config order."""
        ids = [p.model for p in self.players] + [self.narrator.model]
        return list(dict.fromkeys(m for m in ids if is_openrouter_model(m)))

    @property
    def rounds_limit(self) -> int:
        """Number of rounds the clock allows (max_rounds = 0 means players - 2)."""
        return self.game.max_rounds or (len(self.players) - 2)

    def to_dict(self) -> dict:
        d = {
            "game": dict(vars(self.game)),
            "limits": dict(vars(self.limits)),
            "narrator": dict(vars(self.narrator)),
            "players": [dict({"model": p.model, "name": p.name}, **({"role": p.role} if p.role else {}))
                        for p in self.players],
        }
        # Only configs that have the table (or seat an OpenRouter model) log it, so the logged
        # config of an all-Claude game is unchanged.
        if "openrouter" in self.raw or self.openrouter_models():
            d["openrouter"] = self.openrouter.to_dict()
        return d


def display_name(model_id: str) -> str:
    """`claude-opus-5-5` -> `Opus 5.5`, `claude-fable-5` -> `Fable 5`; an OpenRouter id drops its
    vendor: `x-ai/grok-4.7` -> `Grok 4.7`."""
    s = model_id
    if is_openrouter_model(s):
        s = s.split("/", 1)[1] or s
    if s.startswith("claude-"):
        s = s[len("claude-"):]
    parts = s.split("-")
    words = [parts[0].capitalize()] if parts else [model_id]
    rest = parts[1:]
    # Version digits are joined with dots; any non-numeric tail stays as words.
    nums = []
    while rest and re.fullmatch(r"\d+", rest[0]):
        nums.append(rest.pop(0))
    if nums:
        words.append(".".join(nums))
    words.extend(w.capitalize() for w in rest)
    return " ".join(words)


def _build(section_cls, data: dict, section: str):
    data = dict(data or {})
    known = set(section_cls.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"[{section}] unknown keys: {sorted(unknown)}")
    obj = section_cls(**data)
    for name, f in section_cls.__dataclass_fields__.items():
        val = getattr(obj, name)
        default = f.default
        if isinstance(default, bool):
            if not isinstance(val, bool):
                raise ConfigError(f"[{section}] {name} must be true/false")
        elif isinstance(default, (int, float)):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ConfigError(f"[{section}] {name} must be a number")
            if isinstance(default, int) and not isinstance(default, bool) and not isinstance(val, int):
                if name != "call_timeout_s":
                    raise ConfigError(f"[{section}] {name} must be an integer")
            lo = _NEGATIVE_OK.get(name, 0)
            if val < lo:
                raise ConfigError(f"[{section}] {name} must be >= {lo}")
        elif isinstance(default, str) and not isinstance(val, str):
            raise ConfigError(f"[{section}] {name} must be a string")
    return obj


def config_from_dict(raw: dict) -> Config:
    raw = copy.deepcopy(raw)
    unknown = set(raw) - {"game", "limits", "narrator", "players", "openrouter"}
    if unknown:
        raise ConfigError(f"unknown top-level sections: {sorted(unknown)}")
    game = _build(GameConfig, raw.get("game"), "game")
    limits = _build(LimitsConfig, raw.get("limits"), "limits")
    narrator = _build(NarratorConfig, raw.get("narrator"), "narrator")
    openrouter = _build_openrouter(raw.get("openrouter"))

    entries = raw.get("players") or []
    if not isinstance(entries, list):
        raise ConfigError("[[players]] must be an array of tables")
    models = []
    explicit = []
    roles = []
    for i, p in enumerate(entries):
        if not isinstance(p, dict) or not isinstance(p.get("model"), str) or not p["model"]:
            raise ConfigError(f"player {i + 1}: 'model' is required")
        extra = set(p) - {"model", "name", "role"}
        if extra:
            raise ConfigError(f"player {i + 1}: unknown keys {sorted(extra)}")
        check_model_id(p["model"])
        models.append(p["model"])
        explicit.append(p.get("name"))
        r = p.get("role")
        if r is not None and r not in ("mole", "crew"):
            raise ConfigError(f"player {i + 1}: role must be \"mole\" or \"crew\"")
        roles.append(r)

    # Derived names; every copy of a repeated model gets a letter (A, B, ...)
    # in config order. Explicit names are used verbatim.
    counts: dict[str, int] = {}
    for m, n in zip(models, explicit):
        if n is None:
            counts[m] = counts.get(m, 0) + 1
    seen: dict[str, int] = {}
    players = []
    for m, n, r in zip(models, explicit, roles):
        if n is None:
            n = display_name(m)
            if counts[m] > 1:
                n = f"{n} {chr(ord('A') + seen.get(m, 0))}"
                seen[m] = seen.get(m, 0) + 1
        if not isinstance(n, str) or not n.strip():
            raise ConfigError(f"player name for {m} must be a non-empty string")
        players.append(PlayerConfig(model=m, name=n.strip(), role=r))

    names = [p.name for p in players]
    if len(set(names)) != len(names):
        raise ConfigError(f"player names must be unique: {names}")
    if any(n.lower() == "none" for n in names):
        raise ConfigError("'none' is reserved and cannot be a player name")

    cfg = Config(game=game, limits=limits, narrator=narrator, players=players, raw=raw, openrouter=openrouter)
    validate(cfg)
    return cfg


def check_model_id(m: str) -> None:
    """OpenRouter ids (docs/OPENROUTER.md). Claude models always run on the subscription, through
    the CLI: an `anthropic/...` id would bill them through OpenRouter instead."""
    if m.lower().startswith("anthropic/"):
        raise ConfigError(f"model {m!r}: Claude models run through `claude -p` on the subscription, "
                          f"never through OpenRouter; use the Claude id without the \"anthropic/\" prefix")
    if is_openrouter_model(m) and (m.startswith("/") or m.endswith("/") or any(c.isspace() for c in m)):
        raise ConfigError(f"model {m!r} is not a valid OpenRouter id (vendor/model)")


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _tokens(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _build_openrouter(data) -> OpenRouterConfig:
    """The [openrouter] table: budget_usd (> 0), max_output_tokens (integer >= 1), optional
    per-model prices in dollars per million tokens, optional per-model starting output limits
    (max_output_tokens_by_model), the escalation ceiling (max_output_tokens_ceiling), and optional
    per-model reasoning efforts (reasoning_effort_by_model) and providers (providers_by_model)."""
    if data is None:
        return OpenRouterConfig()
    if not isinstance(data, dict):
        raise ConfigError("[openrouter] must be a table")
    unknown = set(data) - {"budget_usd", "max_output_tokens", "prices", "max_output_tokens_by_model",
                           "max_output_tokens_ceiling", "reasoning_effort_by_model", "providers_by_model"}
    if unknown:
        raise ConfigError(f"[openrouter] unknown keys: {sorted(unknown)}")
    out = OpenRouterConfig()
    if data.get("budget_usd") is not None:
        b = data["budget_usd"]
        if not _number(b) or b <= 0:
            raise ConfigError("[openrouter] budget_usd must be a number of dollars > 0")
        out.budget_usd = float(b)
    if "max_output_tokens" in data:
        m = data["max_output_tokens"]
        if isinstance(m, bool) or not isinstance(m, int) or m < 1:
            raise ConfigError("[openrouter] max_output_tokens must be an integer >= 1")
        out.max_output_tokens = m
    prices = data.get("prices") or {}
    if not isinstance(prices, dict):
        raise ConfigError("[openrouter.prices] must be a table of \"vendor/model\" = {input, output}")
    for model, p in prices.items():
        if not is_openrouter_model(model):
            raise ConfigError(f"[openrouter.prices] {model!r} is not an OpenRouter id (vendor/model)")
        if not isinstance(p, dict) or set(p) - {"input", "output"} or not {"input", "output"} <= set(p):
            raise ConfigError(f"[openrouter.prices.\"{model}\"] needs exactly input and output "
                              "(dollars per million tokens)")
        if not all(_number(p[k]) and p[k] >= 0 for k in ("input", "output")):
            raise ConfigError(f"[openrouter.prices.\"{model}\"] input and output must be numbers >= 0")
        out.prices[model] = {"input": float(p["input"]), "output": float(p["output"])}
    limits = data.get("max_output_tokens_by_model")
    limits = {} if limits is None else limits
    if not isinstance(limits, dict):
        raise ConfigError("[openrouter.max_output_tokens_by_model] must be a table of \"vendor/model\" = tokens")
    for model, v in limits.items():
        if not is_openrouter_model(model):
            raise ConfigError(f"[openrouter.max_output_tokens_by_model] {model!r} is not an OpenRouter id "
                              "(vendor/model)")
        check_model_id(model)
        if not _tokens(v):
            raise ConfigError(f"[openrouter.max_output_tokens_by_model] \"{model}\" must be an integer >= 1 "
                              "(output tokens per call, reasoning included)")
        out.max_output_tokens_by_model[model] = v
    starts = [out.max_output_tokens, *out.max_output_tokens_by_model.values()]
    if "max_output_tokens_ceiling" in data:
        c = data["max_output_tokens_ceiling"]
        if not _tokens(c):
            raise ConfigError("[openrouter] max_output_tokens_ceiling must be an integer >= 1")
        if c < max(starts):
            which = ("max_output_tokens" if out.max_output_tokens == max(starts) else
                     "max_output_tokens_by_model \"" + next(m for m, v in out.max_output_tokens_by_model.items()
                                                            if v == max(starts)) + "\"")
            raise ConfigError(f"[openrouter] max_output_tokens_ceiling ({c}) must be at least every starting "
                              f"limit: {which} is {max(starts)}")
        out.max_output_tokens_ceiling = c
    else:
        out.max_output_tokens_ceiling = max(DEFAULT_OUTPUT_CEILING, *starts)
    efforts = data.get("reasoning_effort_by_model")
    efforts = {} if efforts is None else efforts
    if not isinstance(efforts, dict):
        raise ConfigError("[openrouter.reasoning_effort_by_model] must be a table of \"vendor/model\" = effort")
    for model, v in efforts.items():
        if not is_openrouter_model(model):
            raise ConfigError(f"[openrouter.reasoning_effort_by_model] {model!r} is not an OpenRouter id "
                              "(vendor/model)")
        check_model_id(model)
        if not isinstance(v, str) or v not in OPENROUTER_EFFORTS:
            raise ConfigError(f"[openrouter.reasoning_effort_by_model] \"{model}\" must be one of "
                              f"{list(OPENROUTER_EFFORTS)}")
        out.reasoning_effort_by_model[model] = v
    providers = data.get("providers_by_model")
    providers = {} if providers is None else providers
    if not isinstance(providers, dict):
        raise ConfigError("[openrouter.providers_by_model] must be a table of \"vendor/model\" = [provider slugs]")
    for model, v in providers.items():
        if not is_openrouter_model(model):
            raise ConfigError(f"[openrouter.providers_by_model] {model!r} is not an OpenRouter id (vendor/model)")
        check_model_id(model)
        if (not isinstance(v, list) or not v
                or not all(isinstance(s, str) and s and not any(c.isspace() for c in s) for s in v)):
            raise ConfigError(f"[openrouter.providers_by_model] \"{model}\" must be a non-empty list of provider "
                              "slugs (non-empty strings without spaces)")
        dup = next((s for i, s in enumerate(v) if s in v[:i]), None)
        if dup is not None:
            raise ConfigError(f"[openrouter.providers_by_model] \"{model}\" lists provider {dup!r} more than once")
        out.providers_by_model[model] = list(v)
    return out


def validate(cfg: Config) -> None:
    g = cfg.game
    n = len(cfg.players)
    if n < 4:
        raise ConfigError(f"need at least 4 players, got {n}")
    if not (1 <= g.num_moles and g.num_moles < n / 2):
        raise ConfigError(f"num_moles must satisfy 1 <= num_moles < players/2 (got {g.num_moles} for {n} players)")
    if not (1 <= g.job_size <= n):
        raise ConfigError(f"job_size must be between 1 and the number of players (got {g.job_size})")
    if not (1 <= g.job_size_small <= g.job_size):
        raise ConfigError(f"job_size_small must be between 1 and job_size (got {g.job_size_small})")
    if g.clean_target < 1:
        raise ConfigError("clean_target must be >= 1")
    fixed = [p.role for p in cfg.players]
    if any(r is not None for r in fixed):
        if any(r is None for r in fixed):
            raise ConfigError("either every player has a fixed role or none does")
        if fixed.count("mole") != g.num_moles:
            raise ConfigError(f"fixed roles give {fixed.count('mole')} moles but num_moles = {g.num_moles}")
    if g.clue_strength not in CLUE_STRENGTHS:
        raise ConfigError(f"clue_strength must be one of {sorted(CLUE_STRENGTHS)}")
    if g.clue_recipients < 0:
        raise ConfigError("clue_recipients must be >= 0 (0 = every alive player)")
    # clue_recipients = 0 means everyone and ignores the spread (see SPEC "Deviations").
    if g.clue_recipients > 0 and not (0 <= g.clue_recipients_spread <= g.clue_recipients):
        raise ConfigError("clue_recipients_spread must satisfy 0 <= spread <= clue_recipients")
    if g.sabotage_target < 1:
        raise ConfigError("sabotage_target must be >= 1")
    if g.discussion_passes < 1:
        raise ConfigError("discussion_passes must be >= 1")
    if g.whispers and g.whisper_exchanges < 1:
        raise ConfigError("whisper_exchanges must be >= 1 when whispers are on")
    if g.finale_exchanges < 0:
        raise ConfigError("finale_exchanges must be >= 0")
    if g.anonymise and n > len(CODENAMES):
        raise ConfigError(f"anonymise supports at most {len(CODENAMES)} players")
    if g.pot < 0:
        raise ConfigError("pot must be >= 0")
    # v0.4 dials (docs/V04.md). Integer ranges (>= 0) are checked by _build.
    if g.whisper_pairing not in WHISPER_PAIRINGS:
        raise ConfigError(f"whisper_pairing must be one of {list(WHISPER_PAIRINGS)}")
    if g.endings not in ENDINGS:
        raise ConfigError(f"endings must be one of {list(ENDINGS)}")
    if not g.clue_turn and g.whispers and g.whisper_pairing == "chosen":
        raise ConfigError("clue_turn = false needs whispers = false or whisper_pairing = \"random\" "
                          "(chosen whisper partners are asked for in the clue turn)")
    if not g.vote_nobody and g.forced_vote_after != GameConfig.forced_vote_after:
        raise ConfigError("forced_vote_after only applies with vote_nobody = true")
    if g.vote_nobody and any(p.name.lower() == NOBODY for p in cfg.players):
        raise ConfigError(f"'{NOBODY}' is a vote option when vote_nobody = true and cannot be a player name")
    lim = cfg.limits
    if lim.max_parallel_calls < 1:
        raise ConfigError("max_parallel_calls must be >= 1")
    if lim.call_timeout_s <= 0:
        raise ConfigError("call_timeout_s must be > 0")
    for k in ("confessional_words", "public_words", "whisper_words", "memory_words"):
        if getattr(lim, k) < 1:
            raise ConfigError(f"{k} must be >= 1")
    if not (0 <= lim.word_grace <= 1):
        raise ConfigError("word_grace must satisfy 0 <= word_grace <= 1")
    if lim.max_thinking_tokens < -1:
        raise ConfigError("max_thinking_tokens must be >= -1 (-1 = leave MAX_THINKING_TOKENS unset)")
    if lim.effort not in EFFORT_LEVELS + ("",):
        raise ConfigError(f"effort must be one of {list(EFFORT_LEVELS)} or \"\"")
    if cfg.narrator.recap_words < 1:
        raise ConfigError("recap_words must be >= 1")
    for m in [p.model for p in cfg.players] + [cfg.narrator.model]:
        check_model_id(m)
    if cfg.openrouter_models():
        t = lim.max_thinking_tokens
        if t > 0 and cfg.openrouter.max_output_tokens <= t:
            raise ConfigError(f"[openrouter] max_output_tokens ({cfg.openrouter.max_output_tokens}) must be "
                              f"above [limits] max_thinking_tokens ({t}): reasoning counts toward it")
        for m, v in cfg.openrouter.max_output_tokens_by_model.items():
            if t > 0 and v <= t:
                raise ConfigError(f"[openrouter.max_output_tokens_by_model] \"{m}\" ({v}) must be above "
                                  f"[limits] max_thinking_tokens ({t}): reasoning counts toward it")


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return config_from_dict(raw)


def recipient_range(g: "GameConfig", alive: int) -> tuple[int, int] | None:
    """The (low, high) number of clue recipients a round with `alive` players, or None for everyone."""
    if g.clue_recipients == 0:
        return None
    lo = max(0, g.clue_recipients - g.clue_recipients_spread)
    hi = g.clue_recipients + g.clue_recipients_spread
    return min(lo, alive), min(hi, alive)


def parse_set(raw: dict, assignments: list[str]) -> dict:
    """Apply `key=value` overrides to the [game] table of a raw config (for `solve` and `bots`)."""
    raw = copy.deepcopy(raw)
    raw.setdefault("game", {})
    for a in assignments or []:
        if "=" not in a:
            raise ConfigError(f"--set needs key=value, got {a!r}")
        k, v = a.split("=", 1)
        k = k.strip()
        raw["game"][k] = parse_value(k, v.strip())
    return raw


def parse_value(key: str, text: str):
    """A [game] value from text, typed by the field's default."""
    fields = GameConfig.__dataclass_fields__
    if key not in fields:
        raise ConfigError(f"unknown [game] key {key!r}")
    default = fields[key].default
    if isinstance(default, bool):
        if text.lower() in ("true", "1", "yes"):
            return True
        if text.lower() in ("false", "0", "no"):
            return False
        raise ConfigError(f"{key} must be true or false")
    if isinstance(default, int):
        try:
            return int(text)
        except ValueError:
            raise ConfigError(f"{key} must be a whole number") from None
    if isinstance(default, float):
        return float(text)
    return text.strip('"')


def load_raw(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


# RULES.md: "A hidden-role heist game for 7 AI players". bench.toml carries no players, so a trial
# seats this many unless the config's [game] table says otherwise via its players list.
TRIAL_PLAYERS = 7


def trial_config(raw: dict, kind: str, test_model: str, reference_model: str,
                 n_players: int = TRIAL_PLAYERS) -> Config:
    """Build a benchmark-trial config: the test model fills the mole seats (kind="mole") or the
    crew seats (kind="crew"); the reference model fills the rest. Always anonymised. Any
    [[players]] in `raw` are ignored."""
    if kind not in ("mole", "crew"):
        raise ConfigError("trial kind must be 'mole' or 'crew'")
    raw = copy.deepcopy(raw)
    raw.setdefault("game", {})
    raw["game"]["anonymise"] = True
    num_moles = raw["game"].get("num_moles", GameConfig.num_moles)
    test_role, ref_role = ("mole", "crew") if kind == "mole" else ("crew", "mole")
    n_test = num_moles if kind == "mole" else n_players - num_moles
    raw["players"] = ([{"model": test_model, "role": test_role} for _ in range(n_test)] +
                      [{"model": reference_model, "role": ref_role} for _ in range(n_players - n_test)])
    return config_from_dict(raw)
