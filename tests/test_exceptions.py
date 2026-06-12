"""Tests for the exception hierarchy."""

from testops_mirror.exceptions import (
    AuthError,
    ConnectorError,
    NotFoundError,
    RateLimitError,
    TestopsMirrorError,
)


def test_auth_error_is_base():
    assert isinstance(AuthError(), TestopsMirrorError)


def test_not_found_error_is_base():
    assert isinstance(NotFoundError(), TestopsMirrorError)


def test_rate_limit_error_is_base():
    assert isinstance(RateLimitError(), TestopsMirrorError)


def test_connector_error_is_base():
    assert isinstance(ConnectorError(), TestopsMirrorError)


def test_base_is_exception():
    assert isinstance(TestopsMirrorError(), Exception)


def test_message_preserved():
    err = AuthError("token expired")
    assert str(err) == "token expired"


def test_subclasses_are_distinct():
    assert AuthError is not ConnectorError
    assert not isinstance(AuthError(), ConnectorError)
