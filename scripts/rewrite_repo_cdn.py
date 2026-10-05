#!/usr/bin/env python3
"""Rewrite repo.json asset URLs from GitHub raw to CDN (same paths).

Requires ZSTORE_USE_CDN=1. Does not change downloadURL (IPA stays on Releases).
Run after CDN is live and sync_cdn.sh has uploaded files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from catalog_urls import GITHUB_RAW, USE_CDN, rewrite_github_to_cdn

ROOT = Path(__file__).resolve().parent.parent
REPO_JSON = ROOT / "repo.json"


def rewrite_app(app: dict) -> None:
    if app.get("iconURL"):
        app["iconURL"] = rewrite_github_to_cdn(app["iconURL"])
    if app.get("screenshotURLs"):
        app["screenshotURLs"] = [rewrite_github_to_cdn(u) for u in app["screenshotURLs"]]


def main() -> int:
    if not USE_CDN:
        print("Set ZSTORE_USE_CDN=1 to rewrite URLs", file=sys.stderr)
        return 1

    repo = json.loads(REPO_JSON.read_text(encoding="utf-8"))
    for app in repo.get("apps") or []:
        rewrite_app(app)

    text = json.dumps(repo, ensure_ascii=False, indent=2) + "\n"
    if REPO_JSON.read_text(encoding="utf-8") != text:
        REPO_JSON.write_text(text, encoding="utf-8")
        print("repo.json updated")
    else:
        print("repo.json unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
