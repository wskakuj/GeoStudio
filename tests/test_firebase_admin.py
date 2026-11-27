from datetime import datetime, timezone

import pytest

from tools.admin.geostudio_admin import parse_expiry, policy_changes


def policy(old, *, limit=2, removed=()):
    return policy_changes(old, email="tester@example.invalid", name="Test",
                          notes="", active=True, expires=None, limit=limit, removed=removed)


def test_expiry_requires_explicit_zone():
    assert parse_expiry("") is None
    assert parse_expiry("2027-01-31T23:59:00+01:00") == datetime(2027, 1, 31, 22, 59, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        parse_expiry("2027-01-31")


def test_policy_keeps_concurrent_registrations():
    a, b = "a"*64, "b"*64
    result = policy({"devices": [a, b]}, removed=[a])
    assert result["devices"] == [b]
    assert result["deviceLimit"] == 2
    assert result["active"] is True
    assert result["expiresAt"] is None


def test_reducing_device_limit_requires_removing_slots():
    with pytest.raises(ValueError):
        policy({"devices": ["a"*64, "b"*64]}, limit=1)
    assert policy({"devices": ["a"*64, "b"*64]}, limit=1,
                  removed=["a"*64])["devices"] == ["b"*64]


@pytest.mark.parametrize("limit", [0, 2, 20])
@pytest.mark.parametrize("offline,hours", [(False,0),(True,72),(0,0),(72,72),(-1,-1)])
def test_offline_policy_independent_of_device_limit(limit, offline, hours):
    kwargs = dict(email="tester@example.invalid",name="Test",notes="",active=True,
                  expires=None,removed=(),offline=offline)
    assert policy_changes({},limit=limit,**kwargs)["offlineHours"] == hours


@pytest.mark.parametrize("bad", ["-1", -2, 99, None, 72.0])
def test_invalid_offline_policy(bad):
    with pytest.raises(ValueError):
        policy_changes({},email="tester@example.invalid",name="",notes="",active=True,
                       expires=None,removed=(),offline=bad,limit=0)
