from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.editor import Change

INT32_MAX = 2**31 - 1  # Postgres integer: bigger ids would fail in the database with a 500
KeitaroId = Annotated[int, Field(ge=1, le=INT32_MAX)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class CreateCampaignIn(Input):
    # 200 + the 15-char prefix fits the 255-char column, checked before anything is created
    name: str = Field(min_length=1, max_length=200)
    geo: str = Field(max_length=1000)  # "MX,AU,RO"
    offer_id: KeitaroId
    domain_id: KeitaroId
    group_id: KeitaroId
    traffic_source_id: KeitaroId


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


class AddOfferIn(Input):
    offer_id: KeitaroId


class PinIn(Input):
    share: int | None = None  # None pins the current share
