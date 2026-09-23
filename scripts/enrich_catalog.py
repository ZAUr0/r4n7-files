#!/usr/bin/env python3
"""Enrich catalog: HD icons, portrait screenshots, age ratings, reviews."""

from __future__ import annotations

import hashlib
import io
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
REPO_JSON = ROOT / "repo.json"
ICONS_DIR = ROOT / "icons"
SHOTS_DIR = ROOT / "screenshots"

sys.path.insert(0, str(SCRIPTS))
from sync_rustore import parse_reviews, package_from_url, guessed_package  # noqa: E402

RUSTORE_VER = "12000"
INFO_URL = "https://backapi.rustore.ru/applicationData/overallInfo/{package}"
REVIEWS_URL = "https://www.rustore.ru/catalog/app/{package}/reviews"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup?{query}&country={country}&entity=software"
JINA = "https://r.jina.ai/"

ICON_BASE = "https://raw.githubusercontent.com/ZAUr0/r4n7-files/main/icons/"
SHOT_BASE = "https://raw.githubusercontent.com/ZAUr0/r4n7-files/main/screenshots/"

CTX = ssl.create_default_context()
MIN_ICON = 350
TARGET_ICON = 1024
PORTRAIT_W = 1080
PORTRAIT_H = 2340


def request(url: str, headers=None, timeout: int = 25) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ZStoreEnrich/1.0)",
            "Accept": "*/*",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
        return resp.read()


def rustore_info(package: str) -> dict:
    raw = request(
        INFO_URL.format(package=package),
        headers={"Accept": "application/json", "ruStoreVerCode": RUSTORE_VER},
        timeout=20,
    )
    payload = json.loads(raw.decode("utf-8"))
    body = payload.get("body") or {}
    if not isinstance(body, dict) or not body:
        raise RuntimeError("empty overallInfo")
    return body


def rustore_reviews(package: str, limit: int = 6) -> list:
    markdown = ""
    for url, timeout in (
        (REVIEWS_URL.format(package=package), 12),
        (JINA + REVIEWS_URL.format(package=package), 18),
    ):
        try:
            markdown = request(url, timeout=timeout).decode("utf-8", "replace")
            if "Нравится:" in markdown or "Markdown Content:" in markdown:
                break
        except Exception:
            continue
    if not markdown:
        return []
    return parse_reviews(markdown, limit=limit)


def itunes_lookup(bundle=None, name=None):
    queries = []
    if bundle:
        queries.append(f"bundleId={urllib.parse.quote(bundle)}")
    if name:
        queries.append(f"term={urllib.parse.quote(name)}&limit=5")
    if not queries:
        return None
    for country in ("ru", "us", "gb"):
        for query in queries:
            try:
                raw = request(
                    ITUNES_LOOKUP.format(query=query, country=country),
                    timeout=15,
                )
            except Exception:
                continue
            results = (json.loads(raw.decode("utf-8")).get("results") or [])
            if not results:
                continue
            if "bundleId=" in query:
                return results[0]
            needle = (name or "").casefold()
            for item in results:
                if (item.get("trackName") or "").casefold() == needle:
                    return item
            return results[0]
    return None


def save_icon(data: bytes) -> str:
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    # Prefer square icon
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    im = canvas.resize((TARGET_ICON, TARGET_ICON), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    payload = buf.getvalue()
    name = f"{hashlib.md5(payload).hexdigest()[:8]}.png"
    (ICONS_DIR / name).write_bytes(payload)
    return name


def local_icon_min_side(icon_url: str):
    if not icon_url or "/icons/" not in icon_url:
        return None
    path = ICONS_DIR / icon_url.rsplit("/", 1)[-1]
    if not path.exists():
        return None
    try:
        return min(Image.open(path).size)
    except Exception:
        return None


def to_portrait_jpeg(data: bytes) -> bytes:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    target_ratio = PORTRAIT_W / float(PORTRAIT_H)
    if w > h:
        new_w = int(round(h * target_ratio))
        if new_w <= w:
            left = (w - new_w) // 2
            im = im.crop((left, 0, left + new_w, h))
        else:
            new_h = int(round(w / target_ratio))
            top = max(0, (h - new_h) // 2)
            im = im.crop((0, top, w, top + new_h))
    im = im.resize((PORTRAIT_W, PORTRAIT_H), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def save_shot(data: bytes, slug: str, index: int) -> str:
    payload = to_portrait_jpeg(data)
    name = f"{slug}-{index}-{hashlib.md5(payload).hexdigest()[:8]}.jpg"
    (SHOTS_DIR / name).write_bytes(payload)
    return name


def probe_orientation(url: str):
    """Return (w,h) using a small download; None on failure."""
    try:
        data = request(url, timeout=12)
        # only need headers of image — read limited
        im = Image.open(io.BytesIO(data[:120_000] if len(data) > 120_000 else data))
        im.load()
        return im.size
    except Exception:
        try:
            im = Image.open(io.BytesIO(request(url, timeout=15)))
            return im.size
        except Exception:
            return None


def age_from_info(info: dict):
    restriction = info.get("ageRestriction")
    if isinstance(restriction, dict) and restriction.get("category"):
        return str(restriction["category"])
    if info.get("ageLegal") not in (None, ""):
        return str(info["ageLegal"])
    return None


def enrich_app(app: dict, stats: dict) -> None:
    name = app.get("name") or "?"
    pinned = bool(app.get("pinnedScreenshots") or app.get("skipStoreSync"))
    package = package_from_url(app.get("rustoreURL")) or guessed_package(app)
    info = None
    itunes = None

    if package:
        try:
            info = rustore_info(package)
            if not app.get("rustoreURL"):
                app["rustoreURL"] = f"https://www.rustore.ru/catalog/app/{package}"
        except Exception as exc:
            stats["rustore_fail"].append(f"{name}: {exc}")

    if info is None:
        bundles = []
        bid = app.get("bundleIdentifier")
        if bid:
            bundles.append(bid)
            if str(bid).endswith("1"):
                bundles.append(str(bid)[:-1])
        for bundle in bundles:
            try:
                itunes = itunes_lookup(bundle=bundle)
                if itunes:
                    break
            except Exception:
                pass
        if itunes is None:
            try:
                itunes = itunes_lookup(name=str(name).replace("+", "").strip())
            except Exception:
                itunes = None

    # --- icons ---
    min_side = local_icon_min_side(app.get("iconURL") or "")
    if min_side is None or min_side < MIN_ICON:
        icon_bytes = None
        if info and info.get("iconUrl"):
            try:
                icon_bytes = request(info["iconUrl"], timeout=20)
            except Exception as exc:
                stats["icon_fail"].append(f"{name}: {exc}")
        if icon_bytes is None and itunes:
            art = itunes.get("artworkUrl512") or itunes.get("artworkUrl100")
            if art:
                art = art.replace("512x512bb", "1024x1024bb").replace("100x100bb", "1024x1024bb")
                try:
                    icon_bytes = request(art, timeout=20)
                except Exception as exc:
                    stats["icon_fail"].append(f"{name}: {exc}")
        if icon_bytes:
            try:
                fname = save_icon(icon_bytes)
                app["iconURL"] = ICON_BASE + fname
                stats["icons"] += 1
                print(f"  icon -> {fname}", flush=True)
            except Exception as exc:
                stats["icon_fail"].append(f"{name} save: {exc}")

    # --- screenshots ---
    if not pinned:
        source_urls = []
        if info:
            files = [
                item
                for item in (info.get("fileUrls") or [])
                if isinstance(item, dict)
                and item.get("type") == "SCREENSHOT"
                and item.get("fileUrl")
            ]
            files.sort(key=lambda item: item.get("ordinal") or 0)
            source_urls = [item["fileUrl"] for item in files]
        if not source_urls and itunes:
            source_urls = list(itunes.get("screenshotUrls") or [])[:8]

        current = list(app.get("screenshotURLs") or [])
        needs_rebuild = False
        if source_urls and not current:
            needs_rebuild = True
        elif current:
            # Fast heuristic: Apple phone screenshots named Display / landscape tablet dumps
            for url in current:
                low = url.lower()
                if any(x in low for x in ("ipad", "landscape", "12.9", "tablet")):
                    needs_rebuild = True
                    break
                # probe only mzstatic / unknown hosts, max 2
            if not needs_rebuild:
                probed = 0
                for url in current[:2]:
                    if "static.rustore.ru" in url and "/SCREENSHOT/" in url:
                        continue
                    size = probe_orientation(url)
                    probed += 1
                    if size and size[0] > size[1]:
                        needs_rebuild = True
                        break
                    if probed >= 2:
                        break

        if needs_rebuild and source_urls:
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(name)).strip("-").lower()[:40] or "app"
            new_urls = []
            for index, url in enumerate(source_urls[:8], 1):
                try:
                    raw = request(url, timeout=35)
                    # Keep portrait sources as-is hosting? Always normalize to local portrait JPEG
                    size = None
                    try:
                        size = Image.open(io.BytesIO(raw)).size
                    except Exception:
                        pass
                    if size and size[1] >= size[0] and "static.rustore.ru" in url and size[0] >= 700:
                        # already good portrait on CDN
                        new_urls.append(url)
                    else:
                        fname = save_shot(raw, slug, index)
                        new_urls.append(SHOT_BASE + fname)
                except Exception as exc:
                    stats["shot_fail"].append(f"{name}#{index}: {exc}")
            if new_urls:
                app["screenshotURLs"] = new_urls
                stats["shots"] += 1
                print(f"  shots -> {len(new_urls)}", flush=True)

    # --- age ---
    if not app.get("ageRating"):
        age = age_from_info(info) if info else None
        if not age and itunes:
            age = itunes.get("contentAdvisoryRating") or itunes.get("trackContentRating")
            age = str(age) if age else None
        if age:
            app["ageRating"] = age
            stats["age"] += 1
            print(f"  age -> {age}", flush=True)

    # --- reviews ---
    if not (app.get("reviews") or []) and package:
        try:
            reviews = rustore_reviews(package, limit=6)
            if reviews:
                app["reviews"] = reviews
                stats["reviews"] += 1
                print(f"  reviews -> {len(reviews)}", flush=True)
        except Exception as exc:
            stats["review_fail"].append(f"{name}: {exc}")

    # ratings
    if info and isinstance(info.get("rating"), dict):
        rating = info["rating"]
        if app.get("rating") is None and rating.get("average") is not None:
            app["rating"] = rating["average"]
        if app.get("ratingCount") is None and rating.get("votes") is not None:
            app["ratingCount"] = rating["votes"]
    if itunes:
        if app.get("rating") is None and itunes.get("averageUserRating") is not None:
            app["rating"] = itunes["averageUserRating"]
        if app.get("ratingCount") is None and itunes.get("userRatingCount") is not None:
            app["ratingCount"] = itunes["userRatingCount"]


def main() -> int:
    ICONS_DIR.mkdir(exist_ok=True)
    SHOTS_DIR.mkdir(exist_ok=True)
    repo = json.loads(REPO_JSON.read_text(encoding="utf-8"))
    apps = repo.get("apps") or []
    only = {item.casefold() for item in sys.argv[1:]}
    stats = {
        "icons": 0,
        "shots": 0,
        "age": 0,
        "reviews": 0,
        "rustore_fail": [],
        "icon_fail": [],
        "shot_fail": [],
        "review_fail": [],
    }

    for index, app in enumerate(apps, 1):
        name = app.get("name") or app.get("bundleIdentifier") or "?"
        if only and not any(item in str(name).casefold() for item in only):
            continue
        print(f"[{index}/{len(apps)}] {name}", flush=True)
        try:
            enrich_app(app, stats)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {exc}", flush=True)
        # checkpoint every 15 apps
        if index % 15 == 0:
            REPO_JSON.write_text(
                json.dumps(repo, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print("  checkpoint saved", flush=True)

    REPO_JSON.write_text(json.dumps(repo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done",
        f"icons={stats['icons']}",
        f"shots={stats['shots']}",
        f"age={stats['age']}",
        f"reviews={stats['reviews']}",
        flush=True,
    )
    for key in ("rustore_fail", "icon_fail", "shot_fail", "review_fail"):
        rows = stats[key]
        if rows:
            print(key, len(rows), flush=True)
            for row in rows[:20]:
                print(" ", row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
