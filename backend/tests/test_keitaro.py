import json
import re

import httpx
import pytest
import respx

from app.keitaro import USER_AGENT, KeitaroClient, KeitaroError

BASE = "https://keitaro.test/admin_api/v1"


@pytest.fixture
async def client():
    c = KeitaroClient(BASE + "/", "secret-key")
    yield c
    await c.close()


@respx.mock
async def test_sends_api_key_and_honest_user_agent(client):
    route = respx.get(f"{BASE}/groups", params={"type": "campaigns"}).respond(json=[{"id": 1}])
    assert await client.campaign_groups() == [{"id": 1}]
    request = route.calls.last.request
    assert request.headers["Api-Key"] == "secret-key"
    assert request.headers["User-Agent"] == USER_AGENT


@respx.mock
async def test_set_stream_offers_puts_full_offer_list(client):
    route = respx.put(f"{BASE}/streams/5").respond(json={"id": 5})
    offers = [{"offer_id": 1, "share": 100, "state": "active"}]
    await client.set_stream_offers(5, offers)
    assert json.loads(route.calls.last.request.content) == {"offers": offers}


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(404, json={"error": "Campaign not found"}), "(404): Campaign not found"),
        (httpx.Response(422, json={"name": "Name is required"}), "(422): name: Name is required"),
        (httpx.Response(403, text="<html>Cloudflare</html>"), "(403): Forbidden"),
    ],
)
@respx.mock
async def test_error_responses_become_keitaro_errors(client, response, message):
    respx.get(f"{BASE}/campaigns/7").mock(return_value=response)
    with pytest.raises(KeitaroError, match=re.escape(message)):
        await client.campaign(7)


@respx.mock
async def test_network_failure_is_keitaro_error_without_leaking_details(client):
    respx.get(f"{BASE}/offers").mock(side_effect=httpx.ConnectTimeout("timed out"))
    with pytest.raises(KeitaroError, match=r"unreachable \(ConnectTimeout\)") as exc:
        await client.offers()
    assert "secret-key" not in str(exc.value)
