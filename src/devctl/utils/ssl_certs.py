"""Configure SSL CA bundle for HTTPS in dev installs and PyInstaller binaries."""

import os
import ssl
from typing import Any
from urllib.request import Request, urlopen


def _ca_bundle_path() -> str | None:
    try:
        import certifi
    except ImportError:
        return os.environ.get("SSL_CERT_FILE")
    return certifi.where()


def configure_ssl_certs() -> None:
    """Point Python SSL at certifi's CA bundle when the system store is unavailable."""
    ca_bundle = _ca_bundle_path()
    if not ca_bundle:
        return
    os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)


def ssl_context() -> ssl.SSLContext:
    """Return an SSL context that uses certifi's CA bundle."""
    ca_bundle = _ca_bundle_path()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    return ssl.create_default_context()


def open_url(request: Request, timeout: int = 10) -> Any:
    """Open an HTTPS URL using certifi-backed certificate verification."""
    return urlopen(request, timeout=timeout, context=ssl_context())
