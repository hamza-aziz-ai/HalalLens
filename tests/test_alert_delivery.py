#!/usr/bin/env python3
"""Compliance-flip alert emails to subscribers (alerts/delivery.py, D-031), offline."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from alerts import WatchEntry, delivery
from tests.watchlist_fake import MemoryWatchlistStorage

KEY = (1, "TCS", "compliance_flip")
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def _evaluation(verdict, is_compliant, day):
    return {
        "verdict": verdict,
        "is_compliant": is_compliant,
        "filing_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "evaluated_at": datetime(2026, 2, day, tzinfo=timezone.utc),
        "open_issues": False,
    }


HALAL = lambda day=1: _evaluation("compliant", True, day)  # noqa: E731
HARAM = lambda day=2: _evaluation("non-compliant", False, day)  # noqa: E731


def _grant(gid=1, start=NOW - timedelta(days=1), duration=timedelta(days=30), revoked_at=None):
    return {"id": gid, "plan_code": "lifetime" if duration is None else "starter", "source": "razorpay",
            "allocated_at": start, "duration": duration, "revoked_at": revoked_at}


class Mail:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    def __call__(self, to, subject, body, message_id=None):
        if self.fail:
            raise self.fail
        self.sent.append({"to": to, "subject": subject, "body": body, "message_id": message_id})


@pytest.fixture
def world():
    storage = MemoryWatchlistStorage()
    grants = {1: [_grant()], 2: [_grant()], 3: [_grant()]}
    storage.add(WatchEntry(user_id=1, symbol="TCS"))
    storage.filings["TCS"] = HALAL()
    storage.observe("TCS")  # silent baseline

    def run(mail, enabled=True):
        return delivery.run(storage, lambda uid: grants.get(uid, []), enabled=enabled, send=mail,
                            sender="alerts@halallens.test", base_url="https://app.test/")

    return storage, grants, run


def test_seed_is_silent(world):
    storage, _, run = world
    mail = Mail()
    assert run(mail)["sent"] == 0 and mail.sent == []


def test_flip_is_sent_to_the_subscriber_and_acknowledged(world):
    storage, _, run = world
    storage.filings["TCS"] = HARAM()
    mail = Mail()
    counts = run(mail)
    assert counts["flipped"] == 1 and counts["sent"] == 1
    [message] = mail.sent
    assert message["to"] == "user1@example.com"  # the subscriber's own verified address
    assert message["subject"] == "HalalLens: TCS is now non-compliant"
    body = message["body"]
    assert "TCS changed from compliant to non-compliant" in body
    assert "Filing date: 2026-01-01" in body
    assert "https://app.test/analysis?symbol=TCS" in body
    assert "not a fatwa and not investment advice" in body
    assert "Manage alerts: https://app.test/account" in body
    assert message["message_id"].startswith("<alert-") and message["message_id"].endswith("@halallens.test>")
    row = storage.rows[KEY]
    assert row["notified_is_compliant"] is False  # acknowledged
    assert run(Mail())["sent"] == 0  # nothing replays


def test_message_id_is_stable_for_a_resend(world):
    storage, _, _ = world
    storage.filings["TCS"] = HARAM()
    storage.observe("TCS")
    entry = storage.entry(KEY)
    assert delivery.message_id(KEY, entry, "a@x.test") == delivery.message_id(KEY, dict(entry), "a@x.test")
    other = {**entry, "observed_evaluated_at": entry["observed_evaluated_at"] + timedelta(seconds=1)}
    assert delivery.message_id(KEY, entry, "a@x.test") != delivery.message_id(KEY, other, "a@x.test")


def test_verdict_moving_back_during_the_send_leaves_a_corrective_alert_pending(world):
    storage, _, run = world
    storage.filings["TCS"] = HARAM()
    sent = []

    def racing_send(to, subject, body, message_id=None):
        sent.append(subject)
        if len(sent) == 1:  # while B is on the wire, a newer evaluation says A again
            storage.filings["TCS"] = HALAL(day=3)
            storage.observe("TCS", user_id=1)

    run(racing_send)
    row = storage.rows[KEY]
    assert row["notified_is_compliant"] is False and row["last_is_compliant"] is True  # B recorded, A pending
    run(racing_send)
    assert sent == ["HalalLens: TCS is now non-compliant", "HalalLens: TCS is now compliant"]
    assert storage.rows[KEY]["notified_is_compliant"] is True


def test_smtp_failures_back_off_then_stop_and_a_new_target_resets(world):
    storage, _, run = world
    storage.filings["TCS"] = HARAM()
    broken = Mail(fail=OSError("smtp down"))
    counts = run(broken)
    row = storage.rows[KEY]
    assert counts["failed"] == 1 and counts["error:OSError"] == 1
    assert row["notify_attempts"] == 1 and row["notify_next_at"] == NOW + timedelta(minutes=15)
    assert run(broken)["failed"] == 0  # not due yet
    for attempt in range(2, delivery.MAX_ATTEMPTS + 1):
        storage.now = row["notify_next_at"]
        run(broken)
        assert row["notify_attempts"] == attempt
    assert row["notify_failed_at"] is not None  # terminal: never picked again
    storage.now += timedelta(days=2)
    assert run(Mail())["sent"] == 0

    storage.filings["TCS"] = HALAL(day=4)  # back to the notified verdict: nothing to say
    run(Mail())
    storage.filings["TCS"] = HARAM(day=5)  # a new pending target resets the retry state
    mail = Mail()
    assert run(mail)["sent"] == 1 and row["notify_attempts"] == 0 and row["notify_failed_at"] is None


def test_a_failing_row_does_not_starve_the_others(world):
    storage, _, run = world
    storage.add(WatchEntry(user_id=2, symbol="TCS"))
    storage.observe("TCS")
    storage.filings["TCS"] = HARAM()

    def flaky(to, subject, body, message_id=None):
        if to == "user1@example.com":
            raise OSError("mailbox rejected")
        flaky.sent.append(to)

    flaky.sent = []
    counts = run(flaky)
    assert counts["failed"] == 1 and flaky.sent == ["user2@example.com"]
    # The failed row is now behind a later notify_next_at; a fresh flip is first.
    storage.add(WatchEntry(user_id=3, symbol="INFY"))
    storage.filings["INFY"] = HALAL()
    storage.observe("INFY")
    storage.filings["INFY"] = HARAM()
    storage.observe("INFY")
    storage.now += timedelta(hours=1)
    assert storage.pending(5, 50)[0] == (3, "INFY", "compliance_flip")


def test_per_user_cap_and_global_budget(world, monkeypatch):
    storage, grants, run = world
    for symbol in ("A", "B", "C"):
        storage.add(WatchEntry(user_id=1, symbol=symbol))
        storage.add(WatchEntry(user_id=2, symbol=symbol))
        storage.filings[symbol] = HALAL()
    run(Mail())
    for symbol in ("A", "B", "C"):
        storage.filings[symbol] = HARAM()
    monkeypatch.setattr(delivery, "PER_USER_LIMIT", 2)
    monkeypatch.setattr(delivery, "SEND_BUDGET", 3)
    mail = Mail()
    assert run(mail)["sent"] == 3
    per_user = [m["to"] for m in mail.sent]
    assert per_user.count("user1@example.com") <= 2 and per_user.count("user2@example.com") <= 2


@pytest.mark.parametrize("source", [_evaluation("needs-review", None, 3), RuntimeError("db down")])
def test_unknown_or_blocked_source_defers_without_counting_a_failure(world, source):
    storage, _, run = world
    storage.filings["TCS"] = HARAM()
    storage.observe("TCS")
    storage.filings["TCS"] = source
    mail = Mail()
    counts = run(mail)
    row = storage.rows[KEY]
    assert counts["deferred"] == 1 and mail.sent == []
    assert row["notify_attempts"] == 0 and row["notify_next_at"] == NOW + timedelta(hours=1)
    assert row["notified_is_compliant"] is True and row["last_is_compliant"] is False  # still pending


def test_kill_switch_off_rebaselines_silently_and_nothing_replays_on_enable(world):
    storage, _, run = world
    storage.filings["TCS"] = HARAM()
    mail = Mail()
    counts = run(mail, enabled=False)
    assert counts["rebaselined"] == 1 and mail.sent == []
    assert storage.rows[KEY]["notified_is_compliant"] is False
    assert run(mail, enabled=True)["sent"] == 0 and mail.sent == []


@pytest.mark.parametrize(
    "user, grants",
    [
        ({"alert_emails": False}, [_grant()]),  # opted out
        ({"email_verified_at": None}, [_grant()]),  # unverified
        ({}, []),  # never paid
        ({}, [_grant(start=NOW - timedelta(days=60))]),  # lapsed
        ({}, [_grant(duration=None, revoked_at=NOW - timedelta(hours=1))]),  # refunded Lifetime
    ],
)
def test_ineligible_subscribers_are_rebaselined_silently(world, user, grants):
    storage, all_grants, run = world
    storage.users[1] = user
    all_grants[1] = grants
    storage.filings["TCS"] = HARAM()
    mail = Mail()
    assert run(mail)["silenced"] == 1 and mail.sent == []
    assert storage.rows[KEY]["notified_is_compliant"] is False


@pytest.mark.parametrize(
    "user, grants",
    [
        ({}, [_grant(start=NOW - timedelta(days=60)), _grant(2, start=NOW - timedelta(days=40), duration=None)]),
        ({"is_admin": True}, []),  # admins have paid access in the API too
    ],
)
def test_lifetime_overlay_and_admins_receive_alerts(world, user, grants):
    storage, all_grants, run = world
    storage.users[1] = user
    all_grants[1] = grants
    storage.filings["TCS"] = HARAM()
    assert run(Mail())["sent"] == 1


def test_an_observation_error_skips_that_symbol_only(world):
    storage, _, run = world
    storage.add(WatchEntry(user_id=2, symbol="INFY"))
    storage.filings["INFY"] = RuntimeError("db down")
    storage.filings["TCS"] = HARAM()
    counts = run(Mail())
    assert counts["observe_error"] == 1 and counts["sent"] == 1


def test_a_second_sender_without_the_lock_sends_nothing(monkeypatch):
    @contextmanager
    def held(db):
        yield False

    monkeypatch.setattr(delivery, "sender_lock", held)
    mail = Mail()
    counts = delivery.run_locked(object(), enabled=True, send=mail, sender="a@x.test", base_url="https://app.test")
    assert counts == {"skipped_locked": 1} and mail.sent == []
