#!/usr/bin/env python3
"""
Scrape the Don't Starve Fandom Boss Monsters category page and collect all
unique boss page URLs. Saves results to boss_urls.txt and prints them.

Target page: https://dontstarve.fandom.com/wiki/Category:Boss_Monsters

Usage:
  pip install -r requirements.txt
  python3 scrape_boss_urls.py
"""

from __future__ import annotations

import sys
import time
from typing import Iterable, Set
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag, unquote

import requests
from bs4 import BeautifulSoup


CATEGORY_URL = "https://dontstarve.fandom.com/wiki/Category:Boss_Monsters"
OUTPUT_FILE = "boss_urls.txt"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    )
}


def http_get(url: str) -> str:
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def normalize_fandom_url(base_url: str, href: str) -> str | None:
    if not href:
        return None
    absolute = urljoin(base_url, href)
    # Drop URL fragment (e.g., #section) and query params
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)
    if not parsed.scheme.startswith("http"):
        return None
    if "dontstarve.fandom.com" not in parsed.netloc:
        return None
    if not parsed.path.startswith("/wiki/"):
        return None
    # Exclude non-article namespaces such as Category:, File:, Template:, User:, etc.
    page_name = parsed.path[len("/wiki/") :]
    if ":" in page_name:
        return None
    # Rebuild a canonical URL without params/fragments
    canonical = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return unquote(canonical)


def extract_member_links(html: str, base_url: str) -> Set[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: Set[str] = set()

    # Primary: Fandom category items usually use this class
    for a in soup.select("a.category-page__member-link"):
        url = normalize_fandom_url(base_url, a.get("href"))
        if url:
            urls.add(url)

    # Fallback: Look for links within typical content container
    if len(urls) < 30:
        for a in soup.select("#mw-content-text a, a"):
            url = normalize_fandom_url(base_url, a.get("href"))
            if url:
                urls.add(url)

    return urls


def maybe_follow_pagination(html: str, base_url: str) -> Iterable[str]:
    """Yield category page URLs to cover pagination if present."""
    soup = BeautifulSoup(html, "html.parser")
    yielded: Set[str] = set()
    # Current page first
    yield base_url
    yielded.add(base_url)

    # Common pagination selectors
    next_link = soup.select_one('a[rel="next"], a.category-page__pagination-next')
    while next_link:
        next_url = urljoin(base_url, next_link.get("href") or "")
        if not next_url or next_url in yielded:
            break
        yield next_url
        yielded.add(next_url)
        try:
            html = http_get(next_url)
        except Exception:
            break
        soup = BeautifulSoup(html, "html.parser")
        next_link = soup.select_one('a[rel="next"], a.category-page__pagination-next')


def main() -> int:
    try:
        first_html = http_get(CATEGORY_URL)
    except Exception as exc:
        print(f"Failed to fetch category page: {exc}", file=sys.stderr)
        return 2

    all_urls: Set[str] = set()
    for page_url in maybe_follow_pagination(first_html, CATEGORY_URL):
        try:
            html = first_html if page_url == CATEGORY_URL else http_get(page_url)
        except Exception as exc:
            print(f"Warning: failed to fetch page {page_url}: {exc}", file=sys.stderr)
            continue
        urls = extract_member_links(html, page_url)
        all_urls.update(urls)
        # Be a little polite if there were more pages
        time.sleep(0.4)

    sorted_urls = sorted(all_urls)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        for u in sorted_urls:
            fh.write(u + "\n")

    print("Collected URLs ({}):".format(len(sorted_urls)))
    for u in sorted_urls:
        print(u)

    # Expectation from the category page: 37 items
    if len(sorted_urls) != 37:
        print(
            f"Note: expected 37 unique URLs, found {len(sorted_urls)}. "
            f"The page layout may have changed or additional filters may be needed.",
            file=sys.stderr,
        )

    print(f"\nSaved to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


