from boostspace_cli.scenario_builder_helpers import team_connection_map


class _FakeClient:
    def __init__(self, connections):
        self._connections = connections

    def list_connections(self, team_id=None):
        _ = team_id
        return {"connections": self._connections}


def test_team_connection_map_adds_module_specific_google_preferences():
    client = _FakeClient(
        [
            {"id": 164145, "accountType": "oauth", "accountName": "google-restricted"},
            {"id": 147240, "accountType": "oauth", "accountName": "google"},
        ]
    )

    mapping = team_connection_map(client, team_id=123)

    assert mapping["google-sheets:addRow"] == 147240
    assert mapping["google-drive:getAFile"] == 164145
