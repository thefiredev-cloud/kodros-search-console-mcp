"""Offline tests for the property-contained URL checks. No network, no credentials."""

from __future__ import annotations

import pytest

import server as S


@pytest.mark.parametrize(
    ("site_url", "url", "expected"),
    [
        # url-prefix property: same scheme and host, path on a boundary
        ("https://example.com", "https://example.com/sitemap.xml", True),
        ("https://example.com", "https://example.com", True),
        ("https://example.com/", "https://example.com/sitemap.xml", True),
        ("https://example.com/shop", "https://example.com/shop/sitemap.xml", True),
        ("https://example.com/shop", "https://example.com/shop", True),
        # a longer path that merely starts with the same characters is outside
        ("https://example.com/shop", "https://example.com/shopper-sitemap.xml", False),
        # a host that merely starts with the property host is outside
        ("https://example.com", "https://example.com.evil.net/sitemap.xml", False),
        ("https://example.com", "https://www.example.com/sitemap.xml", False),
        # scheme must match for a url-prefix property
        ("https://example.com", "http://example.com/sitemap.xml", False),
        ("http://example.com", "https://example.com/sitemap.xml", False),
        # sc-domain property: host and every subdomain
        ("sc-domain:example.com", "https://example.com/sitemap.xml", True),
        ("sc-domain:example.com", "https://www.example.com/sitemap.xml", True),
        ("sc-domain:example.com", "https://notexample.com/sitemap.xml", False),
        ("sc-domain:example.com", "https://example.com.evil.net/sitemap.xml", False),
    ],
)
def test_url_in_property(site_url: str, url: str, expected: bool) -> None:
    assert S._url_in_property(site_url, url) is expected


def test_sitemap_url_rejects_lookalike_prefix_and_host() -> None:
    with pytest.raises(ValueError, match="url-prefix property"):
        S._sitemap_url("https://example.com/shop", "https://example.com/shopper-sitemap.xml")
    with pytest.raises(ValueError, match="url-prefix property"):
        S._sitemap_url("https://example.com", "https://example.com.evil.net/sitemap.xml")
    with pytest.raises(ValueError, match="sc-domain property"):
        S._sitemap_url("sc-domain:example.com", "https://example.com.evil.net/sitemap.xml")
    with pytest.raises(ValueError, match="full http"):
        S._sitemap_url("https://example.com", "/sitemap.xml")
    assert S._sitemap_url("https://example.com/shop", "https://example.com/shop/s.xml") == (
        "https://example.com/shop/s.xml"
    )
    assert S._sitemap_url("sc-domain:example.com", "https://www.example.com/s.xml") == (
        "https://www.example.com/s.xml"
    )


def test_inspect_url_rejects_url_outside_the_property() -> None:
    # Raises before any Google client is built, so this stays offline.
    with pytest.raises(ValueError, match="inside the property"):
        S.inspect_url("https://example.com", "https://evil.net/page")
    with pytest.raises(ValueError, match="inside the property"):
        S.inspect_url("https://example.com/shop", "https://example.com/shopper/page")
    with pytest.raises(ValueError, match="full http"):
        S.inspect_url("https://example.com", "example.com/page")
