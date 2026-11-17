import re

import pytest

from app.creator import ISO_COUNTRIES, campaign_name, make_alias, parse_geo
from app.errors import InvalidError


def form(**overrides) -> dict:
    return {
        "name": "demo",
        "geo": "mx, AU",
        "offer_id": 12,
        "domain_id": 1813,
        "group_id": 10332,
        "traffic_source_id": 836,
    } | overrides


# ---------------------------------------------------------------- input rules


def test_iso_list_is_complete():
    assert len(ISO_COUNTRIES) == 249
    assert {"MX", "AU", "RO", "PL", "GB", "KG"} <= ISO_COUNTRIES


def test_parse_geo_accepts_any_separators_and_case_and_drops_duplicates():
    assert parse_geo(" mx, au RO;mx,, ") == ["MX", "AU", "RO"]


@pytest.mark.parametrize(("raw", "message"), [(" , ", "empty"), ("MX,UK,XX", "UK, XX")])
def test_parse_geo_rejects_empty_and_unknown_codes(raw, message):
    with pytest.raises(InvalidError, match=message):
        parse_geo(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("demo", "test_kochkurov_demo"), (" test_kochkurov_demo ", "test_kochkurov_demo")],
)
def test_campaign_name_gets_prefix_once(raw, expected):
    assert campaign_name(raw) == expected


@pytest.mark.parametrize("raw", ["  ", "test_kochkurov_"])
def test_campaign_name_rejects_empty(raw):
    with pytest.raises(InvalidError):
        campaign_name(raw)


def test_alias_is_url_safe_and_unique():
    alias = make_alias("test_kochkurov_Demo 1!")
    assert re.fullmatch(r"test-kochkurov-demo-1-[0-9a-f]{6}", alias)
    assert make_alias("test_kochkurov_x") != make_alias("test_kochkurov_x")


# ---------------------------------------------------------------- endpoints


async def test_meta_preselects_fortests(client):
    meta = (await client.get("/api/meta")).json()
    assert (meta["default_domain_id"], meta["default_group_id"], meta["default_traffic_source_id"]) == (
        1813, 10332, 836
    )
    assert [g["name"] for g in meta["groups"]] == ["Other", "FORTESTS"]


async def test_create_sends_confirmed_payloads_and_opens_campaign_in_editor(client, keitaro):
    response = await client.post("/api/campaigns", json=form())
    assert response.status_code == 201, response.text

    (_, campaign), (_, geo_stream), (_, offer_stream) = keitaro.created
    assert campaign == {
        "name": "test_kochkurov_demo",
        "alias": campaign["alias"],
        "type": "position",
        "domain_id": 1813,
        "group_id": 10332,
        "traffic_source_id": 836,
    }
    assert campaign["alias"].startswith("test-kochkurov-demo-")
    assert geo_stream == {
        "campaign_id": 300,
        "type": "regular",
        "name": "Geo to Google",
        "position": 1,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": "https://www.google.com",
        "filters": [{"name": "country", "mode": "accept", "payload": ["MX", "AU"]}],
    }
    assert offer_stream == {
        "campaign_id": 300,
        "type": "regular",
        "name": "Offers",
        "position": 2,
        "schema": "landings",
        "action_type": "http",
        "offers": [{"offer_id": 12, "share": 100, "state": "active"}],
    }

    view = response.json()
    assert (view["id"], view["name"]) == (300, "test_kochkurov_demo")
    geo, offers = view["streams"]
    assert not geo["has_offers"]
    assert [(o["offer_id"], o["share"]) for o in offers["offers"]] == [(12, 100)]
    assert not offers["dirty"]


async def test_failed_stream_rolls_back_campaign(client, keitaro):
    keitaro.fail_stream = 2
    response = await client.post("/api/campaigns", json=form())

    assert response.status_code == 502
    assert "half-created campaign was deleted" in response.json()["detail"]
    assert keitaro.deleted == [300]
    assert (await client.get("/api/campaigns/300")).status_code == 404


async def test_failed_rollback_tells_what_to_clean_up(client, keitaro):
    keitaro.fail_stream, keitaro.fail_delete = 1, True
    response = await client.post("/api/campaigns", json=form())
    assert response.status_code == 502
    assert "delete campaign 300 by hand" in response.json()["detail"]


@pytest.mark.parametrize(
    "overrides", [{"geo": "MX,ZZ"}, {"name": " "}, {"offer_id": 99}], ids=["geo", "name", "offer"]
)
async def test_invalid_form_is_422_before_anything_is_created(client, keitaro, overrides):
    response = await client.post("/api/campaigns", json=form(**overrides))
    assert response.status_code == 422
    assert keitaro.created == []
