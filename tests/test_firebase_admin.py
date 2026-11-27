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
