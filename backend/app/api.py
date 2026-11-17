"""HTTP endpoints: campaign creator and stream offer editor.
Business rules live in app/editor.py and app/creator.py."""

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import creator, editor
from app.config import settings
from app.db import get_session
from app.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from app.keitaro import KeitaroClient
from app.models import Campaign, Stream, StreamOffer
from app.schemas import (
    AddOfferIn,
    CampaignView,
    CreateCampaignIn,
    Item,
    Meta,
    OfferView,
    PinIn,
    StreamView,
)

OFFERS_SCHEMA = "landings"  # Keitaro "Landing pages & offers"; redirect streams have no offers
AUTOCOMPLETE_LIMIT = 20

router = APIRouter(prefix="/api")


def get_keitaro(request: Request) -> KeitaroClient:
    return request.app.state.keitaro


Session = Annotated[AsyncSession, Depends(get_session)]
Keitaro = Annotated[KeitaroClient, Depends(get_keitaro)]


# ---------------------------------------------------------------- views


def stream_view(stream: Stream) -> StreamView:
    rows = stream.offers
    has_offers = stream.schema == OFFERS_SCHEMA
    return StreamView(
        id=stream.id,
        name=stream.name,
        position=stream.position,
        has_offers=has_offers,
        dirty=editor.is_dirty(rows),
        total_share=sum(r.share for r in rows if r.state == editor.ACTIVE),
        push_blocked_reason=editor.push_blocked_reason(rows) if has_offers else None,
        offers=[
            OfferView(
                offer_id=r.offer_id,
                name=r.offer_name,
                state=r.state,
                share=r.share,
                pin=r.pin,
                change=editor.row_change(r),
            )
            for r in rows
        ],
    )


def campaign_view(campaign: Campaign) -> CampaignView:
    return CampaignView(
        id=campaign.id, name=campaign.name, streams=[stream_view(s) for s in campaign.streams]
    )


# ---------------------------------------------------------------- loading


def ensure_ours(campaign_name: str) -> None:
    if not campaign_name.startswith(settings.campaign_prefix):
        raise ForbiddenError(f"Only campaigns named {settings.campaign_prefix}* can be opened")


async def active_offers(keitaro: KeitaroClient) -> list[dict]:
    return [o for o in await keitaro.offers() if o.get("state") == "active"]


async def find_active_offer(keitaro: KeitaroClient, offer_id: int) -> dict:
    offer = next((o for o in await active_offers(keitaro) if o["id"] == offer_id), None)
    if offer is None:
        raise InvalidError(f"Offer {offer_id} is not an active offer in Keitaro")
    return offer


async def load_campaign(session: AsyncSession, campaign_id: int) -> Campaign | None:
    return await session.scalar(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.streams).selectinload(Stream.offers))
    )


async def load_stream(session: AsyncSession, stream_id: int) -> Stream:
    stream = await session.scalar(
        select(Stream).where(Stream.id == stream_id).options(selectinload(Stream.offers))
    )
    if stream is None:
        raise NotFoundError(f"Stream {stream_id} not found, fetch its campaign first")
    return stream


async def edit_stream(
    session: AsyncSession, stream_id: int, action: Callable[[list[StreamOffer]], None]
) -> StreamView:
    """Load, apply one editor action, save. A DomainError leaves the database untouched."""
    stream = await load_stream(session, stream_id)
    action(stream.offers)
    await session.commit()
    return stream_view(stream)


async def sync_campaign(session: AsyncSession, keitaro: KeitaroClient, campaign_id: int) -> CampaignView:
    """Pull the campaign's streams from Keitaro and sync offers (see editor.sync_from_keitaro)."""
    remote = await keitaro.campaign(campaign_id)
    ensure_ours(remote["name"])  # checked before reading the streams
    remote_streams = sorted(await keitaro.campaign_streams(campaign_id), key=lambda s: s["position"])
    names = {o["id"]: o["name"] for o in await keitaro.offers()}

    campaign = await load_campaign(session, campaign_id)
    if campaign is None:
        campaign = Campaign(id=campaign_id, streams=[])
        session.add(campaign)
    campaign.name = remote["name"]

    local = {s.id: s for s in campaign.streams}
    streams = []
    for rs in remote_streams:
        stream = local.get(rs["id"]) or Stream(id=rs["id"], offers=[])
        stream.name, stream.position, stream.schema = rs["name"], rs["position"], rs["schema"]
        editor.sync_from_keitaro(stream.offers, rs.get("offers") or [], names)
        streams.append(stream)
    campaign.streams = streams  # streams deleted in Keitaro are deleted here too

    await session.commit()
    return campaign_view(campaign)


# ---------------------------------------------------------------- lists and creator


def to_items(raw: list[dict]) -> list[Item]:
    return [Item(id=r["id"], name=r["name"]) for r in raw]


def default_id(items: list[Item], name: str) -> int | None:
    return next((i.id for i in items if i.name == name), items[0].id if items else None)


@router.get("/offers")
async def search_offers(keitaro: Keitaro, q: str = "") -> list[Item]:
    """Autocomplete. Offer names start with their id ("25327 Flexacil"), so one
    substring match covers search by id and by name."""
    needle = q.strip().lower()
    found = [o for o in await active_offers(keitaro) if needle in o["name"].lower()]
    return to_items(found[:AUTOCOMPLETE_LIMIT])


@router.get("/meta")
async def meta(keitaro: Keitaro) -> Meta:
    """Dropdown options for the creator form, with defaults preselected."""
    domains, groups, sources = map(
        to_items,
        await asyncio.gather(keitaro.domains(), keitaro.campaign_groups(), keitaro.traffic_sources()),
    )
    return Meta(
        domains=domains,
        groups=groups,
        traffic_sources=sources,
        default_domain_id=domains[0].id if domains else None,
        default_group_id=default_id(groups, settings.default_group),
        default_traffic_source_id=default_id(sources, settings.default_traffic_source),
    )


@router.get("/campaigns")
async def list_campaigns(keitaro: Keitaro) -> list[Item]:
    campaigns = await keitaro.campaigns()
    return to_items([c for c in campaigns if c["name"].startswith(settings.campaign_prefix)])


@router.post("/campaigns", status_code=201)
async def create_campaign(body: CreateCampaignIn, session: Session, keitaro: Keitaro) -> CampaignView:
    """Create in Keitaro, then fetch it so the editor opens right away."""
    name = creator.campaign_name(body.name)
    geo = creator.parse_geo(body.geo)
    await find_active_offer(keitaro, body.offer_id)

    campaign_id = await creator.create_in_keitaro(
        keitaro, name, geo, body.offer_id, body.domain_id, body.group_id, body.traffic_source_id
    )
    return await sync_campaign(session, keitaro, campaign_id)


# ---------------------------------------------------------------- campaign


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, session: Session) -> CampaignView:
    campaign = await load_campaign(session, campaign_id)
    if campaign is None:
        raise NotFoundError(f"Campaign {campaign_id} not fetched yet")
    return campaign_view(campaign)


@router.post("/campaigns/{campaign_id}/fetch")
async def fetch_campaign(campaign_id: int, session: Session, keitaro: Keitaro) -> CampaignView:
    return await sync_campaign(session, keitaro, campaign_id)


# ---------------------------------------------------------------- stream actions


@router.post("/streams/{stream_id}/offers")
async def add_offer(stream_id: int, body: AddOfferIn, session: Session, keitaro: Keitaro) -> StreamView:
    stream = await load_stream(session, stream_id)
    if stream.schema != OFFERS_SCHEMA:
        raise ConflictError("This stream redirects without offers")
    offer = await find_active_offer(keitaro, body.offer_id)
    editor.add_offer(stream.offers, offer["id"], offer["name"])
    await session.commit()
    return stream_view(stream)


@router.delete("/streams/{stream_id}/offers/{offer_id}")
async def remove_offer(stream_id: int, offer_id: int, session: Session) -> StreamView:
    return await edit_stream(session, stream_id, lambda rows: editor.remove_offer(rows, offer_id))


@router.post("/streams/{stream_id}/offers/{offer_id}/restore")
async def restore_offer(stream_id: int, offer_id: int, session: Session) -> StreamView:
    return await edit_stream(session, stream_id, lambda rows: editor.restore_offer(rows, offer_id))


@router.put("/streams/{stream_id}/offers/{offer_id}/pin")
async def pin_offer(stream_id: int, offer_id: int, body: PinIn, session: Session) -> StreamView:
    return await edit_stream(
        session, stream_id, lambda rows: editor.pin_offer(rows, offer_id, body.share)
    )


@router.delete("/streams/{stream_id}/offers/{offer_id}/pin")
async def unpin_offer(stream_id: int, offer_id: int, session: Session) -> StreamView:
    return await edit_stream(session, stream_id, lambda rows: editor.unpin_offer(rows, offer_id))


@router.post("/streams/{stream_id}/cancel")
async def cancel(stream_id: int, session: Session) -> StreamView:
    return await edit_stream(session, stream_id, editor.cancel)


@router.post("/streams/{stream_id}/push")
async def push(stream_id: int, session: Session, keitaro: Keitaro) -> StreamView:
    """Publish the draft. If Keitaro fails, nothing changes here and the stream stays yellow.
    If our commit failed after Keitaro accepted, the next Fetch would reconcile."""
    stream = await load_stream(session, stream_id)
    payload = editor.push_payload(stream.offers)
    await keitaro.set_stream_offers(stream.id, payload)
    editor.mark_published(stream.offers)
    await session.commit()
    return stream_view(stream)
