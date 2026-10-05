"""Public URLs for catalog assets (CDN) vs legacy GitHub raw.

Set ZSTORE_CDN_BASE on CI or locally before build_lite.py, e.g.:
  export ZSTORE_CDN_BASE=https://cdn.zstoreplus.ru

Old zStore builds keep loading repo-lite.json from GitHub; JSON then points
at CDN for icons and screenshots. IPA downloadURL stays on GitHub Releases.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GITHUB_RAW = "https://raw.githubusercontent.com/ZAUr0/r4n7-files/main/"
CDN_BASE = os.environ.get("ZSTORE_CDN_BASE", "https://cdn.zstoreplus.ru").rstrip("/")
USE_CDN = os.environ.get("ZSTORE_USE_CDN", "").lower() in ("1", "true", "yes")

# Folders uploaded to the VDS (see deploy/sync_cdn.sh).
CDN_SYNC_DIRS = (
    "icons",
    "shots",
    "screenshots",
    "about",
    "d0e4/covers",
    "d0e4/icons",
    "d0e4/screenshots",
    "d0e4/videos",
)


def public_base() -> str:
    if USE_CDN:
        return f"{CDN_BASE}/"
    return GITHUB_RAW


def publish_url(relative_path: str) -> str:
    cleaned = relative_path.strip().lstrip("/")
    return f"{public_base()}{cleaned}"


def local_path_from_url(url: str | None) -> Path | None:
    if not url:
        return None
    for prefix in (f"{CDN_BASE}/", GITHUB_RAW):
        if url.startswith(prefix):
            rel = url[len(prefix) :]
            if rel:
                return ROOT / rel
    return None


def is_repo_asset_url(url: str) -> bool:
    if url.startswith(GITHUB_RAW):
        return True
    return USE_CDN and url.startswith(f"{CDN_BASE}/")


def rewrite_github_to_cdn(url: str) -> str:
    if url.startswith(GITHUB_RAW):
        return publish_url(url[len(GITHUB_RAW) :])
    return url
