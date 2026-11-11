"""`calibrate --no-audit`: run a batch's slots and length gate, review nothing (the ceiling check's extension batch)."""
import argparse
import json

from canary import cli, ledger, llm, mixer, sealed, skeptic
from tests.test_mixer import SHORT, short_plan, world  # noqa: F401 (world is a fixture)


def no_audit(world, plan):
    return cli.run_without_audit(world["client"], plan, world["led"], world["table"], world["runs"], world["twins"],
                                 world["plans"], world["tmp"] / "campaign.log")


def test_every_slot_runs_and_is_sealed_but_nothing_is_reviewed(world, monkeypatch):
    monkeypatch.setattr(skeptic, "audit_pending", lambda *a, **k: (_ for _ in ()).throw(AssertionError("audited")))
    outcome = no_audit(world, short_plan())
    assert (outcome["ran"], outcome["skipped"]) == (SHORT, 0)
    assert len([t for t in world["table"].all() if t.details["batch"] == "b"]) == SHORT
    assert len(world["led"].entries(ledger.RAN)) == SHORT
    assert world["led"].entries(ledger.AUDITED) == [] and world["provider"].calls == []
    log = (world["tmp"] / "campaign.log").read_text(encoding="utf-8")
    assert "nothing audited (--no-audit)" in log
    for word in ("canary_measure", "control", "sham"):
        assert word not in log  # the log never names a run type
    # The runs now wait for any reviewer, so a later reaudit finds all of them.
    assert len(skeptic._waiting(world["led"], "skeptic_a")) == SHORT


def test_a_resume_runs_only_what_is_left(world):
    plan = short_plan()
    no_audit(world, plan)
    again = no_audit(world, plan)
    assert again["ran"] == 0 and len(world["table"].all()) == SHORT


def test_the_length_gate_runs_on_padded_plans(world, monkeypatch):
    seen = []
    monkeypatch.setattr(mixer, "batch_length_check", lambda client, led, table, batch, role, runs_dir:
                        seen.append(role) or {"passes": True, "features": {}, "prompts_too_large": 0})
    plan = short_plan()
    no_audit(world, plan)  # the slots first (the fake scripts cannot be padded), then the gate on a padded plan
    plan = {**plan, "length_match": True, "role": "skeptic_d"}
    assert no_audit(world, plan)["length_check"]["passes"] and seen == ["skeptic_d"]
    assert json.loads((world["plans"] / "b.length_check.json").read_text())["passes"]


def calibrate_args(**changes):
    args = dict(batch="ceiling-ext", runs=None, resume=False, pool=None, role="skeptic_a", seed=None, no_audit=False)
    return argparse.Namespace(**{**args, **changes})


def test_the_cli_records_no_audit_in_the_plan_and_refuses_a_resume_with_audits(world, monkeypatch, tmp_path, capsys):
    plans = tmp_path / "sealed_plans"
    monkeypatch.setattr(llm, "LLM", lambda: world["client"])
    monkeypatch.setattr(ledger, "Ledger", lambda: world["led"])
    monkeypatch.setattr(sealed, "SealedTable", lambda: world["table"])
    monkeypatch.setattr(cli.scientist, "seal_unsealed_runs_as_real", lambda led, table: None)
    monkeypatch.setattr(mixer, "plan_path", lambda batch: plans / f"{batch}.json")
    planned = short_plan()
    monkeypatch.setattr(mixer, "plan_batch", lambda name, runs, pool, seed, role: {**planned, "batch": name})
    pool = tmp_path / "pool.json"
    pool.write_text("{}", encoding="utf-8")
    ran = []
    monkeypatch.setattr(cli, "run_without_audit", lambda *a, **k: ran.append(a[1]["batch"]) or
                        {"ran": SHORT, "skipped": 0, "length_check": None})
    monkeypatch.setattr(mixer, "run_batch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("would audit")))
    assert cli.cmd_calibrate(calibrate_args(runs=8, pool=str(pool), no_audit=True)) == 0
    assert json.loads((plans / "ceiling-ext.json").read_text())["no_audit"] is True and ran == ["ceiling-ext"]
    assert cli.cmd_calibrate(calibrate_args(resume=True)) == 2  # resuming without --no-audit is refused
    assert "resume it the same way" in capsys.readouterr().out
    assert cli.cmd_calibrate(calibrate_args(resume=True, no_audit=True)) == 0 and len(ran) == 2
