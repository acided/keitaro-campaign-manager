"""Our database. Campaign and stream ids are Keitaro ids: we only mirror Keitaro entities."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Stream.position"
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int]
    schema: Mapped[str] = mapped_column(String(32))  # "landings" streams carry offers

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    # List order is the UI order (Keitaro returns offers in no stable order).
    offers: Mapped[list["StreamOffer"]] = relationship(
        cascade="all, delete-orphan", order_by="StreamOffer.id"
    )


class StreamOffer(Base):
    """One offer in a stream, with two layers (see app/editor.py):
    draft (`state`, `share`, `pin`) and published (`pub_*`, NULL = never published)."""

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    offer_id: Mapped[int]
    offer_name: Mapped[str] = mapped_column(String(255))

    state: Mapped[str] = mapped_column(String(16))  # "active" / "removed"
    share: Mapped[int]
    pin: Mapped[int | None]  # pinned share, NULL = not pinned

    pub_state: Mapped[str | None] = mapped_column(String(16))
    pub_share: Mapped[int | None]
    pub_pin: Mapped[int | None]
