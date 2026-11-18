"""Offer weights and the draft/publish state machine of one stream. No I/O.

Every StreamOffer row carries two layers:
- published (`pub_state`, `pub_share`, `pub_pin`): what Keitaro has now;
  `pub_state is None` means the row was never published;
- draft (`state`, `share`, `pin`): what the user sees and edits.

A stream is dirty (yellow) when any row's draft differs from its published layer.
Functions take the stream's `offers` list and change it in place. Removing a row
from the list deletes it from the database (delete-orphan relationship).
"""

from collections.abc import Mapping
from typing import Literal

from app.errors import ConflictError, InvalidError, NotFoundError
from app.models import StreamOffer

TOTAL = 100
ACTIVE = "active"  # same word in our draft and in Keitaro
REMOVED = "removed"

Rows = list[StreamOffer]
Change = Literal["added", "removed", "restored", "reweighted"]


# ---------------------------------------------------------------- weights


def split_evenly(total: int, parts: int) -> list[int]:
    """Largest remainder method for equal parts: all remainders are equal,
    so leftover points go to the first parts in order (100 / 3 -> 34, 33, 33)."""
    if parts <= 0:
        return []
    base, leftover = divmod(max(total, 0), parts)
    return [base + 1 if i < leftover else base for i in range(parts)]


def pinned_total(rows: Rows, exclude: StreamOffer | None = None) -> int:
    return sum(r.pin for r in rows if r is not exclude and r.state == ACTIVE and r.pin is not None)


def rebalance(rows: Rows) -> None:
    """Removed rows get 0 (pin kept for Bring back), pinned active rows get their pin,
    the other active rows split what is left evenly, in row order."""
    free = []
    for row in rows:
        if row.state != ACTIVE:
            row.share = 0
        elif row.pin is not None:
            row.share = row.pin
        else:
            free.append(row)
    for row, share in zip(free, split_evenly(TOTAL - pinned_total(rows), len(free))):
        row.share = share


# ---------------------------------------------------------------- read helpers


def find(rows: Rows, offer_id: int) -> StreamOffer | None:
    return next((r for r in rows if r.offer_id == offer_id), None)


def _get(rows: Rows, offer_id: int) -> StreamOffer:
    row = find(rows, offer_id)
    if row is None:
        raise NotFoundError(f"Offer {offer_id} is not in this stream")
    return row


def row_dirty(row: StreamOffer) -> bool:
    return (row.state, row.share, row.pin) != (row.pub_state, row.pub_share, row.pub_pin)


def is_dirty(rows: Rows) -> bool:
    return any(row_dirty(r) for r in rows)


def row_change(row: StreamOffer) -> Change | None:
    """What the pending draft does to this row; the UI colors rows by it."""
    if row.pub_state is None:
        return "added"
    if row.state != row.pub_state:
        return "removed" if row.state == REMOVED else "restored"
    return "reweighted" if row_dirty(row) else None


def push_blocked_reason(rows: Rows) -> str | None:
    active = [r for r in rows if r.state == ACTIVE]
    if not active:
        return "The stream needs at least one active offer"
    total = sum(r.share for r in active)
    if total != TOTAL:
        return f"Active shares sum to {total}%, must be {TOTAL}%. Unpin an offer"
    return None


# ---------------------------------------------------------------- user actions


def add_offer(rows: Rows, offer_id: int, offer_name: str) -> None:
    existing = find(rows, offer_id)
    if existing is not None:
        if existing.state == REMOVED:
            raise ConflictError(f"Offer {offer_id} was removed, use Bring back")
        raise ConflictError(f"Offer {offer_id} is already in this stream")

    rows.append(StreamOffer(offer_id=offer_id, offer_name=offer_name, state=ACTIVE, share=0))
    rebalance(rows)


def remove_offer(rows: Rows, offer_id: int) -> None:
    """Grey the row out (share 0, pin kept). A never-published row is dropped instead."""
    row = _get(rows, offer_id)
    if row.state != ACTIVE:
        raise ConflictError(f"Offer {offer_id} is already removed")

    if row.pub_state is None:
        rows.remove(row)
    else:
        row.state = REMOVED
    rebalance(rows)


def restore_offer(rows: Rows, offer_id: int) -> None:
    """Bring back a removed row; a kept pin comes back with it."""
    row = _get(rows, offer_id)
    if row.state != REMOVED:
        raise ConflictError(f"Offer {offer_id} is not removed")
    if row.pin is not None and pinned_total(rows) + row.pin > TOTAL:
        raise InvalidError(
            f"Offer {offer_id} is pinned at {row.pin}%, pinned shares would exceed {TOTAL}%. "
            "Unpin something first"
        )

    row.state = ACTIVE
    rebalance(rows)


def pin_offer(rows: Rows, offer_id: int, share: int | None = None) -> None:
    """Pin an active row at `share`, or at its current share."""
    row = _get(rows, offer_id)
    if row.state != ACTIVE:
        raise ConflictError(f"Offer {offer_id} is removed, bring it back before pinning")

    value = row.share if share is None else share
    if not 0 <= value <= TOTAL:
        raise InvalidError(f"Share must be between 0 and {TOTAL}")
    if pinned_total(rows, exclude=row) + value > TOTAL:
        raise InvalidError(f"Pinned shares would exceed {TOTAL}%")

    row.pin = value
    rebalance(rows)


def unpin_offer(rows: Rows, offer_id: int) -> None:
    """Allowed on removed rows too, so Bring back returns them unpinned."""
    row = _get(rows, offer_id)
    if row.pin is None:
        raise ConflictError(f"Offer {offer_id} is not pinned")

    row.pin = None
    rebalance(rows)


def cancel(rows: Rows) -> None:
    """Drop never-published rows, reset the rest to their published layer."""
    if not is_dirty(rows):
        raise ConflictError("Nothing to cancel")

    for row in [r for r in rows if r.pub_state is None]:
        rows.remove(row)
    for row in rows:
        row.state, row.share, row.pin = row.pub_state, row.pub_share, row.pub_pin


# ---------------------------------------------------------------- publish


def push_payload(rows: Rows) -> list[dict]:
    """`offers` for `PUT /streams/{id}`. Keitaro replaces the whole list,
    so removed offers are simply left out."""
    if not is_dirty(rows):
        raise ConflictError("Nothing to push")
    reason = push_blocked_reason(rows)
    if reason:
        raise InvalidError(reason)

    return [
        {"offer_id": r.offer_id, "share": r.share, "state": ACTIVE}
        for r in rows
        if r.state == ACTIVE
    ]


def published_matches(rows: Rows, remote: list[dict]) -> bool:
    """Does Keitaro still have what we last fetched or pushed? Push replaces the whole
    offer list, so pushing over a stream edited in Keitaro would silently undo that edit."""
    live = {o["offer_id"]: o["share"] for o in remote if o["state"] == ACTIVE}
    ours = {r.offer_id: r.pub_share for r in rows if r.pub_state == ACTIVE}
    return live == ours


def mark_published(rows: Rows) -> None:
    """Call only after Keitaro accepted the push."""
    for row in rows:
        row.pub_state, row.pub_share, row.pub_pin = row.state, row.share, row.pin


# ---------------------------------------------------------------- fetch


def sync_from_keitaro(rows: Rows, remote: list[dict], offer_names: Mapping[int, str]) -> None:
    """Refresh the published layer from Keitaro's stream `offers` list.

    - offer in Keitaro but not here -> new row (disabled in Keitaro -> removed);
    - offer published here as active but gone from Keitaro -> removed (grey, Bring back);
    - pins are ours only and are never touched; weights are never rebalanced;
    - a clean stream gets its draft reset to the fresh published layer,
      a dirty stream keeps its draft and is now diffed against the fresh state.
    """
    was_dirty = is_dirty(rows)

    for offer in remote:
        live = offer["state"] == ACTIVE
        state, share = (ACTIVE, offer["share"]) if live else (REMOVED, 0)
        row = find(rows, offer["offer_id"])
        if row is None:
            name = offer_names.get(offer["offer_id"], f"Offer {offer['offer_id']}")
            row = StreamOffer(offer_id=offer["offer_id"], offer_name=name, state=state, share=share)
            rows.append(row)
        row.pub_state, row.pub_share = state, share

    remote_ids = {o["offer_id"] for o in remote}
    for row in rows:
        if row.pub_state == ACTIVE and row.offer_id not in remote_ids:
            row.pub_state, row.pub_share = REMOVED, 0

    if not was_dirty:
        for row in rows:
            row.state, row.share, row.pin = row.pub_state, row.pub_share, row.pub_pin
