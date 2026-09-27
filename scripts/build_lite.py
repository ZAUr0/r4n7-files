"""Build the slim catalog that zStore loads first.

repo.json stays the single source of truth (older app builds keep reading it).
From it this script derives:

  repo-lite.json          minified catalog without reviews, screenshots and
                          release notes; descriptions cut for search only;
                          icons point to small thumbnails
  icons/s/<name>.jpg|png  180 px icon thumbnails (PNG only when transparent)
  details/<id>.json       everything the app page needs, per bundle id

Run after every change to repo.json or icons/.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

ROOT = Path(__file__).resolve().parent.parent
RAW_PREFIX = "https://raw.githubusercontent.com/ZAUr0/r4n7-files/main/"

THUMB_DIR = "icons/s"
DETAILS_DIR = "details"
ICON_SIZE = 180
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


def thumbnail(icon_url: str | None, used: set[str]) -> str | None:
    if not icon_url or not icon_url.startswith(RAW_PREFIX):
        return icon_url

    source = ROOT / icon_url[len(RAW_PREFIX):]
    if not source.is_file():
        return icon_url

    digest = hashlib.sha1(source.read_bytes()).hexdigest()[:8]
    try:
        with Image.open(source) as image:
            image.load()
            transparent = has_transparency(image)
            name = f"{source.stem}-{digest}.{'png' if transparent else 'jpg'}"
            target = ROOT / THUMB_DIR / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                image = image.convert("RGBA" if transparent else "RGB")
                image.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                if transparent:
                    image.save(target, "PNG", optimize=True)
                else:
                    image.save(target, "JPEG", quality=85, optimize=True)
    except OSError as error:
        print(f"skip icon {source.name}: {error}", file=sys.stderr)
        return icon_url

    used.add(name)
    return f"{RAW_PREFIX}{THUMB_DIR}/{name}"


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
    lite["iconURL"] = thumbnail(app.get("iconURL"), used_thumbs)
    return lite


def app_details(app: dict) -> dict:
    details = {key: app[key] for key in DETAIL_KEYS if app.get(key)}
    if app.get("versions"):
        details["versions"] = app["versions"]
    if app.get("iconURL"):
        details["iconURL"] = app["iconURL"]
    return details


def prune(directory: Path, keep: set[str]) -> None:
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()


def main() -> int:
    repo = json.loads((ROOT / "repo.json").read_text(encoding="utf-8"))

    used_thumbs: set[str] = set()
    used_details: set[str] = set()
    lite_apps = []

    for app in repo.get("apps") or []:
        lite_apps.append(lite_app(app, used_thumbs))
        bundle_id = app.get("bundleIdentifier")
        if bundle_id:
            name = details_name(bundle_id)
            used_details.add(name)
            write_if_changed(ROOT / DETAILS_DIR / name, dump(app_details(app)) + "\n")

    lite = {key: value for key, value in repo.items() if key != "apps"}
    lite["apps"] = lite_apps
    write_if_changed(ROOT / "repo-lite.json", dump(lite) + "\n")

    prune(ROOT / THUMB_DIR, used_thumbs)
    prune(ROOT / DETAILS_DIR, used_details)

    print(f"lite: {len(lite_apps)} apps, {len(used_thumbs)} thumbnails, {len(used_details)} details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
