"""Tests for SSL certificate configuration."""

import os

import pytest

from devctl.utils import ssl_certs


def test_configure_ssl_certs_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    ssl_certs.configure_ssl_certs()

    assert os.environ.get("SSL_CERT_FILE")
    assert os.environ.get("REQUESTS_CA_BUNDLE")
    assert os.environ["SSL_CERT_FILE"] == os.environ["REQUESTS_CA_BUNDLE"]
    assert os.path.isfile(os.environ["SSL_CERT_FILE"])


def test_ssl_context_verifies_github() -> None:
    from urllib.request import Request

    req = Request(
        "https://api.github.com/repos/workindia/wi-devctl/releases/latest",
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    with ssl_certs.open_url(req, timeout=15) as resp:
        assert resp.status == 200


def test_configure_ssl_certs_does_not_override_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/custom/certs.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/custom/certs.pem")

    ssl_certs.configure_ssl_certs()

    assert os.environ["SSL_CERT_FILE"] == "/custom/certs.pem"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "/custom/certs.pem"
