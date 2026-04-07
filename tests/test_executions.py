import click
import pytest

from boostspace_cli.executions import (
    _find_execution_log,
    _parse_execution_ref,
    _resolve_execution_input,
    _status_text,
)


def test_parse_execution_ref_with_scenario_prefix():
    scenario_id, execution_id = _parse_execution_ref("12345:abc-123")
    assert scenario_id == 12345
    assert execution_id == "abc-123"


def test_parse_execution_ref_with_slash_prefix():
    scenario_id, execution_id = _parse_execution_ref("98765/exec-9")
    assert scenario_id == 98765
    assert execution_id == "exec-9"


def test_find_execution_log_matches_imt_id():
    logs = [
        {"imtId": 10, "status": 1},
        {"imtId": 11, "status": 3},
    ]
    found = _find_execution_log(logs, "11")
    assert found is not None
    assert found["status"] == 3


def test_status_text_handles_numeric_strings():
    assert _status_text("1") == "success"
    assert _status_text(2) == "warning"
    assert _status_text("unknown") == "unknown"


def test_resolve_execution_input_prefers_history_option():
    assert _resolve_execution_input(None, "55") == "55"


def test_resolve_execution_input_requires_single_source():
    with pytest.raises(click.ClickException):
        _resolve_execution_input("a", "b")


def test_resolve_execution_input_requires_value():
    with pytest.raises(click.ClickException):
        _resolve_execution_input(None, None)
