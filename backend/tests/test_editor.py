import pytest

from app import editor as ed
from app.errors import ConflictError, InvalidError, NotFoundError
from app.models import StreamOffer


def published(offer_id: int, share: int, pin: int | None = None) -> StreamOffer:
    """A row that is live in Keitaro with no pending draft."""
    return StreamOffer(
        offer_id=offer_id, offer_name=f"offer {offer_id}",
        state="active", share=share, pin=pin,
        pub_state="active", pub_share=share, pub_pin=pin,
    )  # fmt: skip


def draft(offer_id: int, state: str = "active", pin: int | None = None) -> StreamOffer:
    return StreamOffer(offer_id=offer_id, offer_name="", state=state, share=0, pin=pin)


def remote(*offers: tuple[int, int] | tuple[int, int, str]) -> list[dict]:
    """Keitaro stream `offers` list from (offer_id, share[, state]) tuples."""
    return [{"offer_id": o[0], "share": o[1], "state": o[2] if len(o) > 2 else "active"} for o in offers]


def shares(rows):
    return [r.share for r in rows]


def changes(rows):
    return [ed.row_change(r) for r in rows]


@pytest.fixture
def stream() -> list[StreamOffer]:
    """Three live offers, as Keitaro has them: 34/33/33."""
    return [published(1, 34), published(2, 33), published(3, 33)]


# ---------------------------------------------------------------- weights


@pytest.mark.parametrize(
    ("total", "parts", "expected"),
    [
        (100, 1, [100]),
        (100, 3, [34, 33, 33]),
        (100, 4, [25, 25, 25, 25]),
        (100, 6, [17, 17, 17, 17, 16, 16]),
        (100, 7, [15, 15, 14, 14, 14, 14, 14]),
        (60, 3, [20, 20, 20]),
        (0, 2, [0, 0]),
        (-10, 2, [0, 0]),
        (100, 0, []),
    ],
)
def test_split_evenly(total, parts, expected):
    assert ed.split_evenly(total, parts) == expected


def test_rebalance_removed_get_zero_and_their_pin_does_not_count():
    rows = [draft(1, pin=40), draft(2, state="removed", pin=50), draft(3), draft(4)]
    ed.rebalance(rows)
    assert shares(rows) == [40, 0, 30, 30]
    assert rows[1].pin == 50


def test_rebalance_pins_at_100_leave_zero_for_free_offers():
    rows = [draft(1, pin=100), draft(2)]
    ed.rebalance(rows)
    assert shares(rows) == [100, 0]


# ---------------------------------------------------------------- end-to-end


def test_end_to_end_example_from_plan(stream):
    """34/33/33 -> Add -> 25x4 -> Pin first at 40 -> 40/20/20/20
    -> Remove second -> 40/0/30/30 -> Bring back -> 40/20/20/20 -> Cancel -> 34/33/33."""
    assert not ed.is_dirty(stream)

    ed.add_offer(stream, 4, "offer 4")
    assert shares(stream) == [25, 25, 25, 25]
    assert changes(stream) == ["reweighted", "reweighted", "reweighted", "added"]

    ed.pin_offer(stream, 1, 40)
    assert shares(stream) == [40, 20, 20, 20]

    ed.remove_offer(stream, 2)
    assert shares(stream) == [40, 0, 30, 30]
    assert ed.row_change(stream[1]) == "removed"

    ed.restore_offer(stream, 2)
    assert shares(stream) == [40, 20, 20, 20]

    ed.cancel(stream)
    assert [r.offer_id for r in stream] == [1, 2, 3]
    assert shares(stream) == [34, 33, 33]
    assert [r.pin for r in stream] == [None, None, None]
    assert not ed.is_dirty(stream)


def test_push_then_remove_then_push_keeps_grey_row_in_archive(stream):
    ed.add_offer(stream, 4, "offer 4")
    ed.pin_offer(stream, 1, 40)
    assert ed.push_payload(stream) == [
        {"offer_id": 1, "share": 40, "state": "active"},
        {"offer_id": 2, "share": 20, "state": "active"},
        {"offer_id": 3, "share": 20, "state": "active"},
        {"offer_id": 4, "share": 20, "state": "active"},
    ]
    ed.mark_published(stream)
    assert not ed.is_dirty(stream)

    ed.remove_offer(stream, 2)
    assert [o["offer_id"] for o in ed.push_payload(stream)] == [1, 3, 4]
    ed.mark_published(stream)
    assert stream[1].state == stream[1].pub_state == "removed"
    assert ed.row_change(stream[1]) is None


# ---------------------------------------------------------------- add / remove


def test_add_to_empty_stream_gets_100():
    rows = []
    ed.add_offer(rows, 7, "offer 7")
    assert shares(rows) == [100]
    assert ed.row_change(rows[0]) == "added"


def test_add_existing_is_conflict_and_removed_one_suggests_bring_back(stream):
    with pytest.raises(ConflictError, match="already in this stream"):
        ed.add_offer(stream, 1, "")
    ed.remove_offer(stream, 2)
    with pytest.raises(ConflictError, match="Bring back"):
        ed.add_offer(stream, 2, "")


def test_remove_never_published_row_drops_it_and_stream_is_clean_again(stream):
    ed.add_offer(stream, 4, "offer 4")
    ed.remove_offer(stream, 4)
    assert [r.offer_id for r in stream] == [1, 2, 3]
    assert shares(stream) == [34, 33, 33]
    assert not ed.is_dirty(stream)


def test_remove_twice_is_conflict_and_unknown_is_not_found(stream):
    ed.remove_offer(stream, 1)
    with pytest.raises(ConflictError, match="already removed"):
        ed.remove_offer(stream, 1)
    with pytest.raises(NotFoundError):
        ed.remove_offer(stream, 999)


# ---------------------------------------------------------------- bring back


def test_remove_pinned_keeps_pin_and_bring_back_restores_weight(stream):
    ed.pin_offer(stream, 2, 50)
    assert shares(stream) == [25, 50, 25]
    ed.remove_offer(stream, 2)
    assert shares(stream) == [50, 0, 50]
    assert stream[1].pin == 50
    ed.restore_offer(stream, 2)
    assert shares(stream) == [25, 50, 25]


def test_bring_back_without_other_changes_makes_stream_clean(stream):
    ed.remove_offer(stream, 3)
    ed.restore_offer(stream, 3)
    assert shares(stream) == [34, 33, 33]
    assert not ed.is_dirty(stream)


def test_bring_back_active_offer_is_conflict(stream):
    with pytest.raises(ConflictError, match="not removed"):
        ed.restore_offer(stream, 1)


def test_bring_back_rejected_when_pins_would_exceed_100(stream):
    ed.pin_offer(stream, 2, 60)
    ed.remove_offer(stream, 2)
    ed.pin_offer(stream, 1, 50)
    with pytest.raises(InvalidError, match="exceed"):
        ed.restore_offer(stream, 2)
    assert stream[1].state == "removed"


# ---------------------------------------------------------------- pin


def test_pin_without_value_pins_current_share_and_makes_stream_dirty(stream):
    ed.pin_offer(stream, 2)
    assert stream[1].pin == 33
    assert shares(stream) == [34, 33, 33]
    assert ed.row_change(stream[1]) == "reweighted"


def test_pin_survives_add_and_remove(stream):
    ed.pin_offer(stream, 1, 25)
    assert shares(stream) == [25, 38, 37]
    ed.add_offer(stream, 4, "")
    assert shares(stream) == [25, 25, 25, 25]
    ed.add_offer(stream, 5, "")
    assert shares(stream) == [25, 19, 19, 19, 18]
    ed.remove_offer(stream, 3)
    assert shares(stream) == [25, 25, 0, 25, 25]


def test_repin_replaces_own_pin_in_the_limit(stream):
    ed.pin_offer(stream, 1, 80)
    ed.pin_offer(stream, 1, 90)
    assert shares(stream) == [90, 5, 5]


@pytest.mark.parametrize("value", [-1, 101])
def test_pin_out_of_range_is_invalid(stream, value):
    with pytest.raises(InvalidError, match="between"):
        ed.pin_offer(stream, 1, value)


def test_pins_over_100_are_invalid(stream):
    ed.pin_offer(stream, 1, 70)
    with pytest.raises(InvalidError, match="exceed"):
        ed.pin_offer(stream, 2, 31)
    assert stream[1].pin is None


def test_pin_removed_offer_is_conflict(stream):
    ed.remove_offer(stream, 1)
    with pytest.raises(ConflictError):
        ed.pin_offer(stream, 1, 10)


def test_unpin_returns_to_even_split_and_unpinned_is_conflict(stream):
    ed.pin_offer(stream, 1, 50)
    ed.unpin_offer(stream, 1)
    assert shares(stream) == [34, 33, 33]
    assert not ed.is_dirty(stream)
    with pytest.raises(ConflictError):
        ed.unpin_offer(stream, 1)


# ---------------------------------------------------------------- push / cancel


def test_push_and_cancel_on_clean_stream_are_conflicts(stream):
    with pytest.raises(ConflictError, match="Nothing to push"):
        ed.push_payload(stream)
    with pytest.raises(ConflictError, match="Nothing to cancel"):
        ed.cancel(stream)


def test_push_blocked_when_all_pinned_and_sum_not_100(stream):
    for offer_id in (1, 2, 3):
        ed.pin_offer(stream, offer_id, 30)
    assert ed.push_blocked_reason(stream) == "Active shares sum to 90%, must be 100%. Unpin an offer"
    with pytest.raises(InvalidError, match="90%"):
        ed.push_payload(stream)


def test_push_blocked_when_no_active_offers():
    rows = [published(1, 100)]
    ed.remove_offer(rows, 1)
    with pytest.raises(InvalidError, match="at least one active offer"):
        ed.push_payload(rows)


def test_cancel_returns_removed_offer_and_published_pin(stream):
    ed.pin_offer(stream, 1, 25)
    ed.mark_published(stream)
    ed.unpin_offer(stream, 1)
    ed.remove_offer(stream, 1)
    ed.cancel(stream)
    assert shares(stream) == [25, 38, 37]
    assert (stream[0].state, stream[0].pin) == ("active", 25)


# ---------------------------------------------------------------- fetch / sync


def test_sync_first_fetch_imports_keitaro_weights_as_is():
    rows = []
    ed.sync_from_keitaro(rows, remote((10, 50), (11, 30)), {10: "Flexacil"})
    assert shares(rows) == [50, 30]  # no rebalance, Push is blocked until the user acts
    assert [r.offer_name for r in rows] == ["Flexacil", "Offer 11"]
    assert not ed.is_dirty(rows)


def test_sync_offer_deleted_in_keitaro_becomes_removed(stream):
    ed.sync_from_keitaro(stream, remote((1, 50), (3, 50)), {})
    assert [r.state for r in stream] == ["active", "removed", "active"]
    assert shares(stream) == [50, 0, 50]
    assert not ed.is_dirty(stream)
    ed.restore_offer(stream, 2)
    assert ed.row_change(stream[1]) == "restored"


def test_sync_disabled_offer_in_keitaro_shows_as_removed(stream):
    ed.sync_from_keitaro(stream, remote((1, 34), (2, 33, "disabled"), (3, 33), (9, 20, "disabled")), {})
    assert [r.state for r in stream] == ["active", "removed", "active", "removed"]
    assert stream[1].share == stream[3].share == 0
    assert not ed.is_dirty(stream)


def test_sync_keeps_draft_of_dirty_stream_and_diffs_against_fresh_state(stream):
    ed.add_offer(stream, 4, "offer 4")  # draft 25x4
    ed.sync_from_keitaro(stream, remote((1, 50), (2, 50)), {})  # 3 deleted in Keitaro

    assert shares(stream) == [25, 25, 25, 25]
    assert [r.pub_share for r in stream] == [50, 50, 0, None]
    assert changes(stream) == ["reweighted", "reweighted", "restored", "added"]

    ed.cancel(stream)
    assert [r.offer_id for r in stream] == [1, 2, 3]
    assert shares(stream) == [50, 50, 0]


def test_sync_new_offer_in_dirty_stream_mirrors_keitaro_and_keeps_draft_pins(stream):
    ed.pin_offer(stream, 1, 50)
    ed.sync_from_keitaro(stream, remote((1, 34), (2, 33), (3, 33), (9, 10)), {})
    assert (stream[-1].offer_id, stream[-1].share, ed.row_change(stream[-1])) == (9, 10, None)
    assert stream[0].pin == 50


def test_sync_never_touches_pins(stream):
    ed.pin_offer(stream, 1, 34)
    ed.mark_published(stream)
    ed.sync_from_keitaro(stream, remote((1, 34), (2, 66)), {})
    assert stream[0].pin == stream[0].pub_pin == 34
    assert shares(stream) == [34, 66, 0]
