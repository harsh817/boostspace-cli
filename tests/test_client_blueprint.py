from boostspace_cli.client import APIClient


def test_extract_blueprint_from_response_wrapper():
    payload = {"response": {"blueprint": {"flow": [{"id": 1, "module": "gateway:CustomWebHook"}]}}}
    blueprint = APIClient.extract_blueprint(payload)
    assert isinstance(blueprint, dict)
    assert "flow" in blueprint


def test_extract_blueprint_from_string_payload():
    payload = {"blueprint": "{\"flow\":[{\"id\":1,\"module\":\"gateway:CustomWebHook\"}]}"}
    blueprint = APIClient.extract_blueprint(payload)
    assert isinstance(blueprint, dict)
    assert blueprint["flow"][0]["module"] == "gateway:CustomWebHook"
