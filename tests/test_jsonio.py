import json

from boostspace_cli.jsonio import emit_json


def test_emit_json_success_schema(capsys):
    emit_json(data={"id": 1}, meta={"command": "test"})
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"] == {"id": 1}
    assert payload["error"] is None
    assert payload["meta"]["command"] == "test"


def test_emit_json_error_schema(capsys):
    emit_json(ok=False, error="boom", meta={"command": "test"})
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"] == "boom"
    assert payload["meta"]["command"] == "test"
