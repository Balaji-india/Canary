from canary import config

CFG = {
    "roles": {
        "scientist": {"model": "qwen3.5:4b", "fallback": "qwen3:4b", "family": "qwen"},
        "skeptic_a": {"model": "gemma4:e4b", "fallback": "gemma3:4b", "family": "gemma"},
        "skeptic_b": {"model": "phi4-mini", "fallback": "llama3.2:3b", "family": "phi"},
        "mutant_writer": {"use_role": "scientist"},
    }
}


def by_role(installed):
    return {c.role: c for c in config.resolve_roles(CFG, installed)}


def test_preferred_model_wins_over_fallback():
    choice = by_role({"qwen3.5:4b", "qwen3:4b"})["scientist"]
    assert choice.model == "qwen3.5:4b"
    assert not choice.used_fallback


def test_fallback_used_when_preferred_is_missing():
    choice = by_role({"qwen3:4b"})["scientist"]
    assert choice.model == "qwen3:4b"
    assert choice.used_fallback


def test_missing_model_gives_none():
    assert by_role(set())["skeptic_a"].model is None


def test_untagged_model_matches_latest():
    choice = by_role({"phi4-mini:latest"})["skeptic_b"]
    assert choice.model == "phi4-mini:latest"
    assert not choice.used_fallback


def test_alias_roles_are_skipped():
    assert "mutant_writer" not in by_role(set())


def test_family_clash_detected():
    clash = {"roles": {"scientist": {"family": "qwen"}, "skeptic_a": {"family": "qwen"},
                       "skeptic_b": {"family": "phi"}}}
    assert config.family_clashes(clash) == ["skeptic_a"]


def test_shipped_config_has_no_family_clash():
    assert config.family_clashes(config.load_yaml("models.yaml")) == []
