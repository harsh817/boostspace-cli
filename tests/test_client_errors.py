from boostspace_cli.client import APIError


def test_api_error_im015_hint():
    err = APIError(401, "Unauthorized", {"code": "IM015", "message": "Unauthorized"})
    assert "IM015" in str(err)
    assert "boost auth playwright" in str(err)


def test_api_error_sc400_hint():
    err = APIError(400, "Bad Request", {"code": "SC400", "message": "Validation failed"})
    assert "SC400" in str(err)
    assert "validation" in str(err).lower()
