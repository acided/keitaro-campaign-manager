from tests.conftest import FOREIGN, GEO_STREAM, OFFER_STREAM, OURS, keitaro_offer

OFFERS = f"/api/streams/{OFFER_STREAM}/offers"


async def fetch(client) -> dict:
    response = await client.post(f"/api/campaigns/{OURS}/fetch")
    assert response.status_code == 200, response.text
    return response.json()


def offer_stream(campaign: dict) -> dict:
    return next(s for s in campaign["streams"] if s["id"] == OFFER_STREAM)


def shares(stream: dict) -> list[int]:
    return [o["share"] for o in stream["offers"]]


async def ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- lists and access


async def test_campaign_list_shows_only_ours(client):
    assert (await client.get("/api/campaigns")).json() == [{"id": OURS, "name": "test_kochkurov_demo"}]


async def test_foreign_campaign_is_forbidden_and_its_streams_are_never_read(client, keitaro):
    response = await client.post(f"/api/campaigns/{FOREIGN}/fetch")
    assert response.status_code == 403
    assert keitaro.streams_read == []


async def test_keitaro_failure_is_502(client):
    response = await client.post("/api/campaigns/999/fetch")
    assert response.status_code == 502
    assert "404" in response.json()["detail"]


async def test_offer_search_by_name_or_id(client):
    assert [o["id"] for o in (await client.get("/api/offers", params={"q": "offer 1"})).json()] == [
        11, 12, 13, 14, 15
    ]
    assert (await client.get("/api/offers", params={"q": "14"})).json() == [{"id": 14, "name": "14 Offer 14"}]


async def test_not_fetched_campaign_and_unknown_stream_are_404(client):
    assert (await client.get(f"/api/campaigns/{OURS}")).status_code == 404
    assert (await client.post("/api/streams/777/cancel")).status_code == 404


# ---------------------------------------------------------------- fetch


async def test_fetch_shows_redirect_stream_without_editor_and_offers_with_weights(client):
    campaign = await fetch(client)
    geo, offers = campaign["streams"]
    assert (geo["id"], geo["has_offers"], geo["offers"], geo["push_blocked_reason"]) == (
        GEO_STREAM, False, [], None
    )
    assert offers["has_offers"] and not offers["dirty"]
    assert [(o["offer_id"], o["name"], o["share"]) for o in offers["offers"]] == [
        (11, "11 Offer 11", 34), (12, "12 Offer 12", 33), (13, "13 Offer 13", 33)
    ]  # fmt: skip
    assert (await client.get(f"/api/campaigns/{OURS}")).json() == campaign


async def test_offer_deleted_in_keitaro_turns_grey_and_deleted_stream_disappears(client, keitaro):
    await fetch(client)
    keitaro.streams[OURS][1]["offers"] = [keitaro_offer(11, 50), keitaro_offer(13, 50)]
    del keitaro.streams[OURS][0]

    campaign = await fetch(client)
    assert [s["id"] for s in campaign["streams"]] == [OFFER_STREAM]
    stream = offer_stream(campaign)
    assert [(o["offer_id"], o["state"], o["share"]) for o in stream["offers"]] == [
        (11, "active", 50), (12, "removed", 0), (13, "active", 50)
    ]  # fmt: skip
    assert not stream["dirty"]


# ---------------------------------------------------------------- editor scenario


async def test_scenario_add_pin_remove_bring_back_push(client, keitaro):
    await fetch(client)

    stream = await ok(await client.post(OFFERS, json={"offer_id": 14}))
    assert shares(stream) == [25, 25, 25, 25]
    assert stream["dirty"] and stream["offers"][-1]["change"] == "added"
    assert keitaro.pushes == []  # nothing reaches Keitaro before Push

    stream = await ok(await client.put(f"{OFFERS}/11/pin", json={"share": 40}))
    assert shares(stream) == [40, 20, 20, 20]

    stream = await ok(await client.delete(f"{OFFERS}/12"))
    assert shares(stream) == [40, 0, 30, 30]
    assert stream["offers"][1]["state"] == "removed"

    stream = await ok(await client.post(f"{OFFERS}/12/restore"))
    assert shares(stream) == [40, 20, 20, 20]

    stream = await ok(await client.post(f"/api/streams/{OFFER_STREAM}/push"))
    assert not stream["dirty"]
    assert keitaro.pushes == [(OFFER_STREAM, [
        keitaro_offer(11, 40), keitaro_offer(12, 20), keitaro_offer(13, 20), keitaro_offer(14, 20)
    ])]  # fmt: skip

    # Fetch after Push sees exactly what we published and keeps the pin.
    stream = offer_stream(await fetch(client))
    assert shares(stream) == [40, 20, 20, 20]
    assert (stream["dirty"], stream["offers"][0]["pin"]) == (False, 40)


async def test_remove_then_push_drops_offer_from_keitaro_but_keeps_grey_row(client, keitaro):
    await fetch(client)
    await client.delete(f"{OFFERS}/13")
    stream = await ok(await client.post(f"/api/streams/{OFFER_STREAM}/push"))
    assert keitaro.pushes[-1] == (OFFER_STREAM, [keitaro_offer(11, 50), keitaro_offer(12, 50)])
    assert (stream["offers"][2]["state"], stream["offers"][2]["change"]) == ("removed", None)

    stream = await ok(await client.post(f"{OFFERS}/13/restore"))
    assert stream["offers"][2]["change"] == "restored"


async def test_cancel_restores_published_state_and_deletes_added_rows(client):
    await fetch(client)
    await client.post(OFFERS, json={"offer_id": 14})
    await client.delete(f"{OFFERS}/12")

    stream = await ok(await client.post(f"/api/streams/{OFFER_STREAM}/cancel"))
    assert [o["offer_id"] for o in stream["offers"]] == [11, 12, 13]
    assert shares(stream) == [34, 33, 33] and not stream["dirty"]
    assert offer_stream((await client.get(f"/api/campaigns/{OURS}")).json()) == stream


async def test_failed_push_keeps_stream_yellow(client, keitaro):
    await fetch(client)
    await client.post(OFFERS, json={"offer_id": 14})
    keitaro.fail_push = True

    response = await client.post(f"/api/streams/{OFFER_STREAM}/push")
    assert response.status_code == 502
    stream = offer_stream((await client.get(f"/api/campaigns/{OURS}")).json())
    assert stream["dirty"] and shares(stream) == [25, 25, 25, 25]


async def test_fetch_keeps_draft_of_yellow_stream(client):
    await fetch(client)
    await client.post(OFFERS, json={"offer_id": 14})
    stream = offer_stream(await fetch(client))
    assert stream["dirty"] and shares(stream) == [25, 25, 25, 25]


# ---------------------------------------------------------------- errors


async def test_action_errors(client):
    await fetch(client)
    cases = [
        (client.post(OFFERS, json={"offer_id": 11}), 409),  # already in stream
        (client.post(OFFERS, json={"offer_id": 99}), 422),  # not an active Keitaro offer
        (client.post(f"/api/streams/{GEO_STREAM}/offers", json={"offer_id": 14}), 409),  # redirect
        (client.delete(f"{OFFERS}/99"), 404),
        (client.post(f"{OFFERS}/11/restore"), 409),  # not removed
        (client.put(f"{OFFERS}/11/pin", json={"share": 101}), 422),
        (client.delete(f"{OFFERS}/11/pin"), 409),  # not pinned
        (client.post(f"/api/streams/{OFFER_STREAM}/push"), 409),  # nothing to push
        (client.post(f"/api/streams/{OFFER_STREAM}/cancel"), 409),  # nothing to cancel
    ]
    for request, status in cases:
        response = await request
        assert response.status_code == status, (response.request.url, response.text)
        assert response.json()["detail"]


async def test_push_blocked_when_pins_do_not_sum_to_100(client, keitaro):
    await fetch(client)
    for offer_id in (11, 12, 13):
        stream = await ok(await client.put(f"{OFFERS}/{offer_id}/pin", json={"share": 30}))
    assert stream["total_share"] == 90
    assert "90%" in stream["push_blocked_reason"]

    response = await client.post(f"/api/streams/{OFFER_STREAM}/push")
    assert response.status_code == 422
    assert keitaro.pushes == []


# ---------------------------------------------------------------- security


async def test_ids_beyond_postgres_integer_are_422_not_500(client):
    for request in (
        client.get("/api/campaigns/99999999999"),
        client.post("/api/streams/99999999999/push"),
        client.delete(f"{OFFERS}/0"),
        client.post(OFFERS, json={"offer_id": 2**31}),
    ):
        assert (await request).status_code == 422


async def test_unknown_host_and_cross_site_writes_are_refused(client, keitaro):
    await fetch(client)
    await client.post(OFFERS, json={"offer_id": 14})
    push = f"/api/streams/{OFFER_STREAM}/push"

    assert (await client.get("/api/campaigns", headers={"Host": "rebound.example"})).status_code == 400
    assert (await client.post(push, headers={"Origin": "https://evil.example"})).status_code == 403
    assert keitaro.pushes == []
    assert (await client.post(push, headers={"Origin": "http://localhost:8080"})).status_code == 200


async def test_push_refuses_campaign_renamed_in_keitaro(client, keitaro):
    await fetch(client)
    await client.post(OFFERS, json={"offer_id": 14})
    keitaro.campaigns_[OURS]["name"] = "someone_elses_now"

    response = await client.post(f"/api/streams/{OFFER_STREAM}/push")
    assert response.status_code == 403
    assert keitaro.pushes == []


async def test_push_refuses_stream_edited_in_keitaro_since_fetch(client, keitaro):
    await fetch(client)
    await client.post(OFFERS, json={"offer_id": 14})
    keitaro.streams[OURS][1]["offers"].append(keitaro_offer(15, 0))  # a colleague added an offer

    response = await client.post(f"/api/streams/{OFFER_STREAM}/push")
    assert response.status_code == 409
    assert "Fetch first" in response.json()["detail"]
    assert keitaro.pushes == []

    stream = offer_stream(await fetch(client))  # Fetch keeps the draft and picks up offer 15
    assert stream["dirty"] and 15 in [o["offer_id"] for o in stream["offers"]]
