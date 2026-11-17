from pydantic import BaseModel

from app.editor import Change


class Item(BaseModel):
    """An offer, campaign, domain, group or traffic source in a list or dropdown."""

    id: int
    name: str


class Meta(BaseModel):
    domains: list[Item]
    groups: list[Item]
    traffic_sources: list[Item]
    default_domain_id: int | None
    default_group_id: int | None
    default_traffic_source_id: int | None


class CreateCampaignIn(BaseModel):
    name: str
    geo: str  # "MX,AU,RO"
    offer_id: int
    domain_id: int
    group_id: int
    traffic_source_id: int


class OfferView(BaseModel):
    offer_id: int
    name: str
    state: str  # "active" / "removed" (grey)
    share: int
    pin: int | None
    change: Change | None  # pending draft change of this row, None = as in Keitaro


class StreamView(BaseModel):
    id: int
    name: str
    position: int
    has_offers: bool  # False for redirect/action streams: shown without an editor
    dirty: bool  # yellow: the draft differs from Keitaro
    total_share: int
    push_blocked_reason: str | None
    offers: list[OfferView]


class CampaignView(BaseModel):
    id: int
    name: str
    streams: list[StreamView]


class AddOfferIn(BaseModel):
    offer_id: int


class PinIn(BaseModel):
    share: int | None = None  # None pins the current share
