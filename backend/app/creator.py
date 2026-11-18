"""Campaign creator: name + geo + offer -> Keitaro campaign with two streams.

Stream 1 sends the given countries to Google, stream 2 sends everyone else to the offer.
Payloads are the ones confirmed by the write probe on the live instance (2026-11-17).
"""

import re
import secrets

from app.config import settings
from app.errors import InvalidError
from app.keitaro import KeitaroClient, KeitaroError

GEO_REDIRECT_URL = "https://www.google.com"

ISO_COUNTRIES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS
BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE
EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM
HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC
LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA
NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA
SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR
TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())  # ISO 3166-1 alpha-2


def parse_geo(raw: str) -> list[str]:
    """"mx, au RO,mx" -> ["MX", "AU", "RO"]: any separators and case, duplicates dropped."""
    codes = list(dict.fromkeys(c.upper() for c in re.split(r"[\s,;]+", raw) if c))
    if not codes:
        raise InvalidError("Geo is empty, expected country codes like MX,AU,RO")
    unknown = [c for c in codes if c not in ISO_COUNTRIES]
    if unknown:
        raise InvalidError(f"Unknown country codes: {', '.join(unknown)}")
    return codes


def campaign_name(raw: str) -> str:
    """Our campaigns must start with the prefix; it is added when missing."""
    name = raw.strip()
    if any(not c.isprintable() for c in name):
        raise InvalidError("Name contains control characters")
    if not name.startswith(settings.campaign_prefix):
        name = settings.campaign_prefix + name
    if name == settings.campaign_prefix:
        raise InvalidError("Name is empty")
    return name


def make_alias(name: str) -> str:
    """Keitaro alias is the campaign token in URLs, so it must be unique and URL-safe."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug}-{secrets.token_hex(3)}"


async def create_in_keitaro(
    keitaro: KeitaroClient,
    name: str,
    geo: list[str],
    offer_id: int,
    domain_id: int,
    group_id: int,
    traffic_source_id: int,
) -> int:
    """Create the campaign and its two streams. If a stream fails, the campaign is
    deleted so no half-created campaign stays in their Keitaro. Returns the campaign id."""
    campaign = await keitaro.create_campaign({
        "name": name,
        "alias": make_alias(name),
        "type": "position",
        "domain_id": domain_id,
        "group_id": group_id,
        "traffic_source_id": traffic_source_id,
    })  # fmt: skip
    campaign_id = campaign["id"]
    streams = [
        {
            "campaign_id": campaign_id,
            "type": "regular",
            "name": "Geo to Google",
            "position": 1,
            "schema": "redirect",
            "action_type": "http",
            "action_payload": GEO_REDIRECT_URL,
            "filters": [{"name": "country", "mode": "accept", "payload": geo}],
        },
        {
            "campaign_id": campaign_id,
            "type": "regular",
            "name": "Offers",
            "position": 2,
            "schema": "landings",
            "action_type": "http",
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        },
    ]
    try:
        for payload in streams:
            await keitaro.create_stream(payload)
    except KeitaroError as exc:
        raise await rollback(keitaro, campaign_id, exc.message) from exc
    return campaign_id


async def rollback(keitaro: KeitaroClient, campaign_id: int, reason: str) -> KeitaroError:
    """Delete our campaign after a failed creation step; returns the error to raise."""
    try:
        await keitaro.delete_campaign(campaign_id)
    except KeitaroError:
        return KeitaroError(f"{reason}. Rollback failed too: delete campaign {campaign_id} by hand")
    return KeitaroError(f"{reason}. The half-created campaign was deleted")
