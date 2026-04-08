import json

from click.testing import CliRunner

import boostspace_cli.config as config_mod
import boostspace_cli.scenario_builder as scenario_builder_mod
from boostspace_cli.cli import main
from boostspace_cli.scenario_swarm import run_parallel_agents, run_swarm


def test_run_parallel_agents_captures_error_and_success():
    jobs = {
        "ok_agent": lambda: {"value": 1},
        "bad_agent": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    }
    rows = run_parallel_agents(jobs, max_workers=2)
    assert len(rows) == 2
    ok = next(item for item in rows if item["agent"] == "ok_agent")
    bad = next(item for item in rows if item["agent"] == "bad_agent")
    assert ok["ok"] is True
    assert bad["ok"] is False
    assert "boom" in bad["error"]


def test_run_swarm_build_requires_goal(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")
    config = config_mod.Config()
    try:
        run_swarm(
            mode="build",
            config=config,
            team_id=None,
            goal=None,
            scenario_id=None,
            scenario_name=None,
            folder_name=None,
            parallelism=2,
            cache_ttl=60,
        )
        assert False, "run_swarm should raise ValueError when build goal missing"
    except ValueError as exc:
        assert "--goal" in str(exc)


def test_scenario_swarm_json_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    def fake_run_swarm(**_kwargs):
        return {
            "mode": "build",
            "parallelism": 4,
            "agents": [{"agent": "planner", "ok": True, "error": None, "durationSeconds": 0.01, "data": {"steps": ["x"]}}],
            "okAgents": 1,
            "failedAgents": 0,
            "durationSeconds": 0.01,
        }

    monkeypatch.setattr(scenario_builder_mod, "run_swarm", fake_run_swarm)

    runner = CliRunner()
    result = runner.invoke(main, ["scenario", "swarm", "--mode", "build", "--goal", "create lead flow", "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "scenario swarm"
    assert payload["data"]["mode"] == "build"
