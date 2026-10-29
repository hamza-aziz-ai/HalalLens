"""The entitlement fold (api/billing.py, D-024): pure, frozen-clock cases."""

from datetime import datetime, timedelta, timezone

from api.billing import current_segment, fold, lifetime_held, project, purchase_start, upcoming

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def grant(gid, plan, at_day, days, *, source="razorpay", revoked_day=None):
    return {
        "id": gid,
        "plan_code": plan,
        "source": source,
        "allocated_at": T0 + at_day * DAY,
        "duration": None if days is None else days * DAY,
        "revoked_at": None if revoked_day is None else T0 + revoked_day * DAY,
    }


def spans(grants):
    return [(s.plan_code, (s.start - T0).days, None if s.end is None else (s.end - T0).days) for s in fold(grants)]


def test_switch_to_a_lower_plan_starts_when_the_current_one_ends():
    # Annual on day 0, Starter bought on day 30: Annual is not cut short.
    assert spans([grant(1, "annual", 0, 365), grant(2, "starter", 30, 30)]) == [
        ("annual", 0, 365),
        ("starter", 365, 395),
    ]


def test_extend_and_upgrade_stack_without_losing_days():
    assert spans([grant(1, "starter", 0, 30), grant(2, "starter", 10, 30), grant(3, "annual", 20, 365)]) == [
        ("starter", 0, 30),
        ("starter", 30, 60),
        ("annual", 60, 425),
    ]


def test_purchase_after_a_gap_starts_at_payment():
    assert spans([grant(1, "starter", 0, 30), grant(2, "starter", 100, 30)]) == [
        ("starter", 0, 30),
        ("starter", 100, 130),
    ]


def test_lifetime_bought_during_a_timed_period_follows_it_and_ends_the_chain():
    assert spans([grant(1, "annual", 0, 365), grant(2, "lifetime", 10, None), grant(3, "starter", 20, 30)]) == [
        ("annual", 0, 365),
        ("lifetime", 365, None),
    ]


def test_refund_of_the_current_grant_ends_it_and_the_next_starts_at_full_length():
    # Codex's counterexample: Annual refunded on day 180 must leave Starter 180-210,
    # not move it back to day 30.
    assert spans([grant(1, "annual", 0, 365, revoked_day=180), grant(2, "starter", 30, 30)]) == [
        ("annual", 0, 180),
        ("starter", 180, 210),
    ]


def test_refund_of_a_queued_grant_takes_no_time_and_never_shortens_the_current_one():
    # Codex's second counterexample: the clamp keeps the timeline moving forward.
    assert spans(
        [grant(1, "annual", 0, 365), grant(2, "starter", 10, 30, revoked_day=60), grant(3, "annual", 90, 365)]
    ) == [("annual", 0, 365), ("starter", 365, 365), ("annual", 365, 730)]


def test_refund_of_an_expired_grant_changes_nothing_else():
    assert spans([grant(1, "starter", 0, 30, revoked_day=200), grant(2, "starter", 100, 30)]) == [
        ("starter", 0, 30),
        ("starter", 100, 130),
    ]


def test_projection_follows_the_clock_through_queued_grants():
    grants = [grant(1, "annual", 0, 365), grant(2, "starter", 30, 30)]
    assert project(grants, T0 + 10 * DAY)["plan"] == "annual"
    later = project(grants, T0 + 370 * DAY)
    assert later["plan"] == "starter" and later["subscription_renewal"] == T0 + 395 * DAY
    assert project(grants, T0 + 400 * DAY) == {
        "plan": "free",
        "subscription_status": "inactive",
        "subscription_renewal": None,
        "plan_started_at": None,
    }
    # Exact boundary: the first grant ends at day 365, the next starts then.
    assert project(grants, T0 + 365 * DAY)["plan"] == "starter"


def test_trial_then_purchase_keeps_the_trial():
    grants = [grant(1, "starter", 0, 30, source="trial"), grant(2, "annual", 5, 365)]
    assert project(grants, T0 + 6 * DAY)["subscription_status"] == "trialing"
    assert project(grants, T0 + 31 * DAY)["plan"] == "annual"


def test_lifetime_held_and_purchase_start():
    timed = [grant(1, "annual", 0, 365)]
    assert not lifetime_held(timed)
    assert purchase_start(timed, T0 + 10 * DAY) == T0 + 365 * DAY
    assert purchase_start(timed, T0 + 400 * DAY) == T0 + 400 * DAY
    assert lifetime_held(timed + [grant(2, "lifetime", 10, None)])  # scheduled counts
    assert not lifetime_held([grant(2, "lifetime", 10, None, revoked_day=11)])


def test_upcoming_hides_refunded_queued_grants():
    segments = fold([grant(1, "annual", 0, 365), grant(2, "starter", 10, 30, revoked_day=60)])
    assert [s.plan_code for s in upcoming(segments, T0 + 100 * DAY)] == ["annual"]
    assert current_segment(segments, T0 + 365 * DAY) is None
