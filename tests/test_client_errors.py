from boostspace_cli.client import APIError


def test_api_error_im015_hint():
    err = APIError(401, "Unauthorized", {"code": "IM015", "message": "Unauthorized"})
    assert "IM015" in str(err)
    assert "boost auth playwright" in str(err)


def test_api_error_sc400_hint():
    err = APIError(400, "Bad Request", {"code": "SC400", "message": "Validation failed"})
    assert "SC400" in str(err)
    assert "validation" in str(err).lower()


def test_api_error_im007_surfaces_detail_message():
    err = APIError(
        400,
        "Bad Request",
        {"code": "IM007", "detail": "Provided account '164145' is not compatible with 'google-sheets:addRow' module."},
    )
    text = str(err)
    assert "IM007" in text
    assert "Invalid blueprint/module" in text
    assert "Provided account '164145' is not compatible" in text


def test_api_error_sc400_surfaces_suberror_message():
    err = APIError(
        400,
        "Bad Request",
        {"code": "SC400", "suberrors": [{"message": "Field 'sheetId' is required."}]},
    )
    text = str(err)
    assert "SC400" in text
    assert "Request validation failed" in text
    assert "Field 'sheetId' is required." in text
