"""Load the YAML configs and work out which model each role uses.

Why this lives in one place: every module must agree on paths and on the model chosen for a role, and
the rule "the Skeptic is a different model family from the Scientist" should be checked once, in code.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "canary.db"


@dataclass(frozen=True)
class RoleChoice:
    """The outcome of matching one role's configured models against the installed ones."""

    role: str
    model: str | None  # None when neither the preferred model nor the fallback is installed
    preferred: str
    fallback: str | None

    @property
    def used_fallback(self) -> bool:
        return self.model is not None and self.model != _with_tag(self.preferred)


_yaml_cache: dict[tuple[Path, int], dict] = {}


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict:
    """Read a config, parsing it again only if the file changed, since hot paths call this for every run.

    Each caller gets its own copy, so changing the result cannot affect later callers.
    """
    path = config_dir / name
    key = (path, path.stat().st_mtime_ns)
    if key not in _yaml_cache:
        with path.open(encoding="utf-8") as f:
            _yaml_cache[key] = yaml.safe_load(f)
    return copy.deepcopy(_yaml_cache[key])


def _with_tag(model: str) -> str:
    """Ollama lists an untagged model such as 'phi4-mini' as 'phi4-mini:latest'."""
    return model if ":" in model else f"{model}:latest"


def resolve_roles(models_cfg: dict, installed: set[str]) -> list[RoleChoice]:
    """Pick the preferred model for each role, else its fallback, else None.

    Aliases (`use_role`) are skipped: they run on the model of the role they point to.
    """
    installed = {_with_tag(m) for m in installed}
    choices = []
    for role, cfg in models_cfg["roles"].items():
        if "use_role" in cfg:
            continue
        candidates = [cfg["model"], cfg.get("fallback")]
        found = next((_with_tag(c) for c in candidates if c and _with_tag(c) in installed), None)
        choices.append(RoleChoice(role, found, cfg["model"], cfg.get("fallback")))
    return choices


def family_clashes(models_cfg: dict) -> list[str]:
    """Return the Skeptic roles that share a model family with the Scientist (should be empty)."""
    roles = models_cfg["roles"]
    scientist = roles["scientist"]["family"]
    # Aliases (`use_role`) have no family of their own: they share the one of the role they point to.
    return [r for r, cfg in roles.items() if r.startswith("skeptic") and "use_role" not in cfg and cfg["family"] == scientist]
