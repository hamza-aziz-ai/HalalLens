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


def test_lifetime_bought_during_annual_takes_effect_at_settlement():
    grants = [grant(1, "annual", 0, 365), grant(2, "lifetime", 10, None)]
    assert spans(grants) == [("annual", 0, 365), ("lifetime", 10, None)]
    assert project(grants, T0 + 10 * DAY - timedelta(seconds=1))["plan"] == "annual"
    at_settlement = project(grants, T0 + 10 * DAY)  # exact boundary: now == allocated_at
    assert at_settlement == {
        "plan": "lifetime",
        "subscription_status": "active",
        "subscription_renewal": None,
        "plan_started_at": T0 + 10 * DAY,
    }
    assert [s.plan_code for s in upcoming(fold(grants), T0 + 11 * DAY)] == ["lifetime"]
    assert project(grants, T0 + 400 * DAY)["plan"] == "lifetime"


def test_trial_then_lifetime_takes_effect_at_settlement():
    grants = [grant(1, "starter", 0, 14, source="trial"), grant(2, "lifetime", 3, None)]
    assert project(grants, T0 + 3 * DAY)["plan"] == "lifetime"
    assert project(grants, T0 + 3 * DAY)["subscription_status"] == "active"


def test_lifetime_after_the_annual_expired_starts_at_settlement():
    grants = [grant(1, "annual", 0, 365), grant(2, "lifetime", 400, None)]
    assert spans(grants) == [("annual", 0, 365), ("lifetime", 400, None)]
    assert project(grants, T0 + 399 * DAY)["plan"] == "free"
    assert project(grants, T0 + 400 * DAY)["plan"] == "lifetime"


def test_lifetime_refunded_mid_annual_reveals_the_annual_with_its_original_end():
    grants = [grant(1, "annual", 0, 365), grant(2, "lifetime", 10, None, revoked_day=50)]
    assert spans(grants) == [("annual", 0, 365), ("lifetime", 10, 50)]
    # Before the refund the (refunded) Lifetime still covered: a finite end is not "timed".
    assert project(grants, T0 + 49 * DAY)["plan"] == "lifetime"
    after = project(grants, T0 + 50 * DAY)  # exact boundary: now == revoked_at
    assert after["plan"] == "annual" and after["subscription_renewal"] == T0 + 365 * DAY
    assert [s.plan_code for s in upcoming(fold(grants), T0 + 60 * DAY)] == ["annual"]
    assert not lifetime_held(grants)
    assert purchase_start(grants, T0 + 60 * DAY) == T0 + 365 * DAY


def test_lifetime_refunded_after_the_annual_expired_leaves_free():
    grants = [grant(1, "annual", 0, 365), grant(2, "lifetime", 10, None, revoked_day=400)]
    assert project(grants, T0 + 399 * DAY)["plan"] == "lifetime"
    assert project(grants, T0 + 400 * DAY)["plan"] == "free"
    assert upcoming(fold(grants), T0 + 400 * DAY) == []


def test_queued_timed_grants_keep_their_dates_under_lifetime():
    grants = [grant(1, "annual", 0, 365), grant(2, "starter", 20, 30), grant(3, "lifetime", 30, None)]
    assert spans(grants) == [("annual", 0, 365), ("lifetime", 30, None), ("starter", 365, 395)]
    assert purchase_start(grants, T0 + 40 * DAY) == T0 + 395 * DAY  # Lifetime never moves the timed chain
    assert project(grants, T0 + 370 * DAY)["plan"] == "lifetime"
    refunded = grants[:2] + [grant(3, "lifetime", 30, None, revoked_day=370)]
    assert spans(refunded) == [("annual", 0, 365), ("lifetime", 30, 370), ("starter", 365, 395)]
    after = project(refunded, T0 + 370 * DAY)
    assert after["plan"] == "starter" and after["subscription_renewal"] == T0 + 395 * DAY


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
