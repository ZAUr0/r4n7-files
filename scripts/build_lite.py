"""Build the slim catalog that zStore loads first.

repo.json stays the single source of truth (older app builds keep reading it).
From it this script derives:

  repo-lite.json          minified catalog without reviews, screenshots and
                          release notes; descriptions cut for search only;
                          icons point to small thumbnails
  icons/s/<name>.jpg|png  180 px icon thumbnails for lists (PNG only when transparent)
  icons/m/<name>.jpg|png  360 px icons for the app page
  shots/<hash>.jpg        screenshots re-encoded to 1600 px JPEG (RuStore / App Store
                          originals are 0.5-3 MB PNGs); originals are kept on failure
  details/<id>.json       everything the app page needs, per bundle id

When ZSTORE_USE_CDN=1, public URLs in JSON use ZSTORE_CDN_BASE (default
https://cdn.zstoreplus.ru). Run deploy/sync_cdn.sh to upload icons/ and shots/.

Run after every change to repo.json or icons/.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageFile

from catalog_urls import GITHUB_RAW, local_path_from_url, publish_url

ImageFile.LOAD_TRUNCATED_IMAGES = True

ROOT = Path(__file__).resolve().parent.parent

THUMB_DIR = "icons/s"
PAGE_ICON_DIR = "icons/m"
SHOTS_DIR = "shots"
DETAILS_DIR = "details"
ICON_SIZE = 180
PAGE_ICON_SIZE = 360
SHOT_MAX_SIDE = 1600
SHOT_QUALITY = 80
DESCRIPTION_LIMIT = 300
DETAIL_KEYS = ("localizedDescription", "reviews", "screenshotURLs", "versionDescription")


def details_name(bundle_id: str) -> str:
    """Must match CatalogAppDetails.fileName(for:) in the app."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", bundle_id) + ".json"


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_if_changed(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def has_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "P"):
        return False
    return image.convert("RGBA").getchannel("A").getextrema()[0] < 250


def resized_icon(icon_url: str | None, used: set[str], directory: str, side: int) -> str | None:
    if not icon_url:
        return icon_url

    source = local_path_from_url(icon_url)
    if source is None and icon_url.startswith(GITHUB_RAW):
        source = ROOT / icon_url[len(GITHUB_RAW) :]
    if source is None or not source.is_file():
        return icon_url

    digest = hashlib.sha1(source.read_bytes()).hexdigest()[:8]
    try:
        with Image.open(source) as image:
            image.load()
            transparent = has_transparency(image)
            name = f"{source.stem}-{digest}.{'png' if transparent else 'jpg'}"
            target = ROOT / directory / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                image = image.convert("RGBA" if transparent else "RGB")
                image.thumbnail((side, side), Image.LANCZOS)
                if transparent:
                    image.save(target, "PNG", optimize=True)
                else:
                    image.save(target, "JPEG", quality=85, optimize=True)
    except OSError as error:
        print(f"skip icon {source.name}: {error}", file=sys.stderr)
        return icon_url

    used.add(name)
    return publish_url(f"{directory}/{name}")


def shot_name(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"


def _hosted_shot(url: str) -> bool:
    rel = local_path_from_url(url)
    if rel is None:
        return False
    parts = rel.parts
    return SHOTS_DIR in parts or "screenshots" in parts


def mirror_shot(url: str) -> bool:
    target = ROOT / SHOTS_DIR / shot_name(url)
    if target.exists():
        return True
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 zStore-catalog"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((SHOT_MAX_SIDE, SHOT_MAX_SIDE), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=SHOT_QUALITY, optimize=True, progressive=True)
    except Exception as error:  # network or decode failure: keep the original URL
        print(f"skip shot {url}: {error}", file=sys.stderr)
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(buffer.getvalue())
    return True


def mirror_shots(repo: dict) -> set[str]:
    urls = sorted({
        url
        for app in repo.get("apps") or []
        for url in app.get("screenshotURLs") or []
        if isinstance(url, str) and url.startswith("http") and not _hosted_shot(url)
    })
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = pool.map(mirror_shot, urls)
    return {url for url, ok in zip(urls, results) if ok}


def short_description(text: str | None) -> str | None:
    if not text or len(text) <= DESCRIPTION_LIMIT:
        return text
    cut = text[:DESCRIPTION_LIMIT]
    space = cut.rfind(" ")
    return cut[:space] if space > DESCRIPTION_LIMIT // 2 else cut


def lite_app(app: dict, used_thumbs: set[str]) -> dict:
    lite = {key: value for key, value in app.items() if key not in DETAIL_KEYS}
    if app.get("localizedDescription"):
        lite["localizedDescription"] = short_description(app["localizedDescription"])
    if app.get("versions"):
        lite["versions"] = [
            {key: value for key, value in version.items() if key != "localizedDescription"}
            for version in app["versions"]
        ]
    lite["iconURL"] = resized_icon(app.get("iconURL"), used_thumbs, THUMB_DIR, ICON_SIZE)
    return lite


def app_details(app: dict, mirrored: set[str], used_page_icons: set[str]) -> dict:
    details = {key: app[key] for key in DETAIL_KEYS if app.get(key)}
    if app.get("screenshotURLs"):
        shot_urls = []
        for url in app["screenshotURLs"]:
            if url in mirrored:
                shot_urls.append(publish_url(f"{SHOTS_DIR}/{shot_name(url)}"))
            elif _hosted_shot(url):
                shot_urls.append(publish_url(local_path_from_url(url).relative_to(ROOT).as_posix()))
            else:
                shot_urls.append(url)
        details["screenshotURLs"] = shot_urls
    if app.get("versions"):
        details["versions"] = app["versions"]
    if app.get("iconURL"):
        details["iconURL"] = resized_icon(app.get("iconURL"), used_page_icons, PAGE_ICON_DIR, PAGE_ICON_SIZE)
    return details


def prune(directory: Path, keep: set[str]) -> None:
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()


def main() -> int:
    repo = json.loads((ROOT / "repo.json").read_text(encoding="utf-8"))

    mirrored = mirror_shots(repo)

    used_thumbs: set[str] = set()
    used_page_icons: set[str] = set()
    used_details: set[str] = set()
    lite_apps = []

    for app in repo.get("apps") or []:
        lite_apps.append(lite_app(app, used_thumbs))
        bundle_id = app.get("bundleIdentifier")
        if bundle_id:
            name = details_name(bundle_id)
            used_details.add(name)
            details = app_details(app, mirrored, used_page_icons)
            write_if_changed(ROOT / DETAILS_DIR / name, dump(details) + "\n")

    lite = {key: value for key, value in repo.items() if key != "apps"}
    lite["apps"] = lite_apps
    write_if_changed(ROOT / "repo-lite.json", dump(lite) + "\n")

    prune(ROOT / THUMB_DIR, used_thumbs)
    prune(ROOT / PAGE_ICON_DIR, used_page_icons)
    prune(ROOT / SHOTS_DIR, {shot_name(url) for url in mirrored})
    prune(ROOT / DETAILS_DIR, used_details)

    print(
        f"lite: {len(lite_apps)} apps, {len(used_thumbs)} thumbnails, "
        f"{len(used_page_icons)} page icons, {len(mirrored)} screenshots, {len(used_details)} details"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
