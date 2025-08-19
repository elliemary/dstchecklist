#!/usr/bin/env python3
"""
Download main boss images from each URL in boss_urls.txt and save them
into ../../bosses as PNG files (prefer PNG sources).

Relies on:
  - scraping/boss_urls.txt produced by scrape_boss_urls.py
  - requests, beautifulsoup4
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag, unquote

import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO


ROOT = Path(__file__).resolve().parents[1]
SCRAPING_DIR = ROOT / "scraping"
URLS_FILE = SCRAPING_DIR / "boss_urls.txt"
OUTPUT_DIR = ROOT / "bosses"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    )
}


def http_get(url: str) -> requests.Response:
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=25)
    resp.raise_for_status()
    return resp


def normalize_image_url(raw: str) -> str:
    """Prefer full-size revision/latest url and PNG if available."""
    if not raw:
        return raw
    raw, _ = urldefrag(raw)
    parsed = urlparse(raw)
    # Only keep dont-starve-game static media
    if "static.wikia.nocookie.net" not in parsed.netloc:
        return raw
    # Remove any scale-to-width-down segment
    path = re.sub(r"/scale-to-width-down/\d+", "", parsed.path)
    # Ensure we target the revision/latest variant
    if "/revision/" not in path:
        if path.endswith(".png") or path.endswith(".jpg") or path.endswith(".jpeg"):
            path = path + "/revision/latest"
    parsed = parsed._replace(path=path, query=parsed.query)
    # Keep cb param if present for cache-busting
    return urlunparse(parsed)


def pick_best_image_url(soup: BeautifulSoup) -> Optional[str]:
    # 1) OpenGraph image (often good quality)
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get("content"):
        cand = normalize_image_url(og["content"])
        if cand.lower().endswith(".png"):
            return cand
        og_png = re.sub(r"\.(jpg|jpeg)(?=($|\?))", ".png", cand, flags=re.IGNORECASE)
        return normalize_image_url(og_png)

    # 2) Portable infobox thumbnail
    for sel in [
        ".portable-infobox .pi-image-thumbnail",
        "figure.pi-item.pi-image img",
        "a.image img",
    ]:
        img = soup.select_one(sel)
        if img and img.get("src"):
            src = normalize_image_url(img["src"])
            if src.lower().endswith(".png"):
                return src
            # try data-src if lazy-loaded
            if img.get("data-src"):
                src2 = normalize_image_url(img["data-src"]) 
                if src2.lower().endswith(".png"):
                    return src2
                return src2
            return src
    return None


def filename_from_image_url(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if name == "latest":
        # path like .../Ancient_Guardian.png/revision/latest
        parent_name = Path(parsed.path).parent.parent.name or fallback
        base = Path(parent_name).stem
    else:
        base = Path(name).stem
    # Force png extension as requested
    return f"{base}.png"


API_ENDPOINT = "https://dontstarve.fandom.com/api.php"


def get_page_image_via_api(title: str) -> Optional[str]:
    """Try PageImages first, fall back to images list and pick a likely main image."""
    try:
        r = requests.get(
            API_ENDPOINT,
            params={
                "action": "query",
                "titles": title,
                "prop": "pageimages",
                "piprop": "original",
                "format": "json",
            },
            headers=REQUEST_HEADERS,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for _, page in pages.items():
            original = page.get("original")
            if original and original.get("source"):
                return original["source"]
    except Exception:
        pass

    # Fallback: list images on page and pick .png matching title if possible
    try:
        r = requests.get(
            API_ENDPOINT,
            params={
                "action": "query",
                "titles": title,
                "prop": "images",
                "imlimit": "max",
                "format": "json",
            },
            headers=REQUEST_HEADERS,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        image_titles = []
        for _, page in pages.items():
            for im in page.get("images", []) or []:
                t = im.get("title", "")
                if t.lower().endswith(('.png', '.jpg', '.jpeg')):
                    image_titles.append(t)
        # Prefer exact base name match PNG
        base = title.split(':')[-1]
        preferred = None
        for t in image_titles:
            name = t.replace('File:', '')
            if name.lower().startswith(base.lower()) and name.lower().endswith('.png'):
                preferred = t
                break
        if not preferred and image_titles:
            # fallback to first PNG else first image
            preferred = next((t for t in image_titles if t.lower().endswith('.png')), image_titles[0])

        if preferred:
            # fetch direct URL via imageinfo
            r2 = requests.get(
                API_ENDPOINT,
                params={
                    "action": "query",
                    "titles": preferred,
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "format": "json",
                },
                headers=REQUEST_HEADERS,
                timeout=20,
            )
            r2.raise_for_status()
            d2 = r2.json()
            pages2 = d2.get("query", {}).get("pages", {})
            for _, p2 in pages2.items():
                infos = p2.get("imageinfo", [])
                if infos:
                    return infos[0].get("url")
    except Exception:
        pass
    return None


def main() -> int:
    if not URLS_FILE.exists():
        print(f"Missing {URLS_FILE}. Run scrape_boss_urls.py first.", file=sys.stderr)
        return 2
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with URLS_FILE.open("r", encoding="utf-8") as fh:
        urls = [line.strip() for line in fh if line.strip()]

    total = 0
    for boss_url in urls:
        try:
            # Derive page title from URL path after /wiki/
            path = urlparse(boss_url).path
            title = path.split('/wiki/', 1)[1]
        except Exception:
            title = boss_url
        # Prefer API to avoid 403 and pick canonical image
        img_url = get_page_image_via_api(title)
        if not img_url:
            # Fallback to HTML scrape if API fails
            try:
                page = http_get(boss_url).text
                soup = BeautifulSoup(page, "html.parser")
                img_url = pick_best_image_url(soup)
            except Exception as exc:
                print(f"Skip {boss_url}: {exc}", file=sys.stderr)
                continue
        if not img_url:
            print(f"No image found for {boss_url}", file=sys.stderr)
            continue
        img_url = normalize_image_url(img_url)
        filename = filename_from_image_url(img_url, fallback=Path(urlparse(boss_url).path).name)
        out_path = OUTPUT_DIR / filename

        try:
            resp = http_get(img_url)
            content_type = resp.headers.get('Content-Type', '').lower()
            data = resp.content
            if 'image/png' in content_type:
                with open(out_path, "wb") as f:
                    f.write(data)
            else:
                # Convert to PNG
                try:
                    img = Image.open(BytesIO(data))
                    img.save(out_path, format='PNG')
                except Exception:
                    # As a last resort, save bytes directly
                    with open(out_path, "wb") as f:
                        f.write(data)
            total += 1
            print(f"Saved {out_path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"Failed {boss_url} -> {img_url}: {exc}", file=sys.stderr)
            continue

        time.sleep(0.25)

    print(f"Done. Saved {total} images to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


