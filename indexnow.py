"""Tell Bing and other IndexNow search engines which pages changed.

Takes every URL from the live sitemap and posts it to IndexNow; update.sh runs it after a deploy
that touched pages. The key lives in indexnow.key and is served at /<key>.txt by run_site.py.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

SITE_URL = "https://mediana-research.com"
KEY = (Path(__file__).resolve().parent / "indexnow.key").read_text().strip()


def main() -> int:
    with urllib.request.urlopen(f"{SITE_URL}/sitemap.xml", timeout=30) as r:
        urls = re.findall(r"<loc>(.*?)</loc>", r.read().decode())
    body = json.dumps({
        "host": SITE_URL.split("//")[1],
        "key": KEY,
        "keyLocation": f"{SITE_URL}/{KEY}.txt",
        "urlList": urls,
    }).encode()
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow", body,
        {"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"IndexNow: {len(urls)} URLs sent, HTTP {r.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
