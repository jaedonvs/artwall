#!/usr/bin/env python3
"""Top up a wallpaper folder with public-domain art from museum open-access APIs.

Sources: Art Institute of Chicago, Cleveland Museum of Art, and the Metropolitan
Museum of Art. All three are no-key and flag public-domain/CC0 works.

Stdlib only -- no requests, no venv -- so the scheduled job can't break on a
missing dependency.

    artwall.py                                  # top up using default topics
    artwall.py --topics "ukiyo-e,bauhaus" --add 10
    artwall.py --list
"""

import argparse
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEST = Path.home() / "Pictures" / "Wallpapers"

UA = "artwall/1.0 (personal wallpaper fetcher; stdlib urllib)"
# The Art Institute's IIIF server 403s without this identifying header. They ask
# for a contact channel; set ARTWALL_CONTACT to your own if you'd rather they
# reach you directly about usage.
CONTACT = os.environ.get("ARTWALL_CONTACT", "https://github.com/jaedonvs/artwall")
HEADERS = {"User-Agent": UA, "AIC-User-Agent": f"artwall ({CONTACT})"}

MET = "https://collectionapi.metmuseum.org/public/collection/v1"

# Taste lives here. Passed as full-text search terms to each source.
TOPICS = [
    "post-impressionism",
    "ukiyo-e",
    "japanese woodblock landscape",
    "hudson river school",
    "botanical illustration",
    "art nouveau poster",
    "abstract composition",
    "still life flowers",
]


# --------------------------------------------------------------------------- io


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def slug(text, maxlen=48):
    text = re.sub(r"[^\w\s-]", "", (text or "untitled")).strip()
    return re.sub(r"[\s_-]+", "-", text).lower()[:maxlen] or "untitled"


def jpeg_dims(b):
    """Width/height from a JPEG's SOF marker, given any prefix of the file."""
    i, n = 2, len(b)
    while i + 9 < n:
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(b[i + 7 : i + 9], "big"), int.from_bytes(b[i + 5 : i + 7], "big")
        if m == 0xD8 or m == 0x01 or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        i += 2 + int.from_bytes(b[i + 2 : i + 4], "big")
    return None


def probe_dims(url, timeout=30):
    """Read just enough of a remote JPEG to learn its dimensions."""
    req = urllib.request.Request(url, headers={**HEADERS, "Range": "bytes=0-131071"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return jpeg_dims(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


# ---------------------------------------------------------------------- sources


def aic(topic, limit):
    """Art Institute of Chicago. Search returns full master dimensions."""
    q = urllib.parse.urlencode(
        {
            "q": topic,
            "query[term][is_public_domain]": "true",
            "fields": "id,title,artist_title,image_id,thumbnail",
            "limit": limit,
        }
    )
    for a in get_json(f"https://api.artic.edu/api/v1/artworks/search?{q}").get("data", []):
        t, img = a.get("thumbnail") or {}, a.get("image_id")
        w, h = t.get("width"), t.get("height")
        if not (img and w and h):
            continue
        px = min(w, 6000)  # IIIF: native width, capped to something sane
        yield {
            "source": "aic",
            "id": a["id"],
            "title": a.get("title"),
            "artist": a.get("artist_title"),
            "width": w,
            "height": h,
            "url": f"https://www.artic.edu/iiif/2/{img}/full/{px},/0/default.jpg",
        }


def cma(topic, limit):
    """Cleveland Museum of Art. 'print' is the largest JPEG variant (<=3400px)."""
    q = urllib.parse.urlencode({"q": topic, "cc0": 1, "has_image": 1, "limit": limit})
    for a in get_json(f"https://openaccess-api.clevelandart.org/api/artworks/?{q}").get("data", []):
        p = (a.get("images") or {}).get("print")
        if not isinstance(p, dict) or not p.get("url"):
            continue
        w, h = int(p.get("width") or 0), int(p.get("height") or 0)
        if not (w and h):
            continue
        creators = a.get("creators") or [{}]
        yield {
            "source": "cma",
            "id": a.get("id"),
            "title": a.get("title"),
            "artist": (creators[0].get("description") or "").split("(")[0].strip(),
            "width": w,
            "height": h,
            "url": p["url"],
        }


def met(topic, limit):
    """Metropolitan Museum of Art.

    Search returns bare object IDs and the API never reports image dimensions,
    so each candidate costs one object lookup plus a ranged header read. That is
    why `limit` is much smaller here than for the other two sources.
    """
    q = urllib.parse.urlencode({"q": topic, "isPublicDomain": "true", "hasImages": "true"})
    ids = get_json(f"{MET}/search?{q}").get("objectIDs") or []
    random.shuffle(ids)
    for oid in ids[:limit]:
        try:
            o = get_json(f"{MET}/objects/{oid}")
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            continue
        url = o.get("primaryImage")
        if not url or not o.get("isPublicDomain"):
            continue
        dims = probe_dims(url)
        if not dims:
            continue
        yield {
            "source": "met",
            "id": oid,
            "title": o.get("title"),
            "artist": o.get("artistDisplayName"),
            "width": dims[0],
            "height": dims[1],
            "url": url,
        }


SOURCES = [(aic, 40), (cma, 40), (met, 10)]


# ------------------------------------------------------------------------- main


def wanted(c, min_width, min_ratio):
    return c["width"] >= min_width and c["width"] / c["height"] >= min_ratio


def fetch(c, dest):
    name = f"{c['source']}-{c['id']}-{slug(c.get('artist'))}-{slug(c.get('title'))}.jpg"
    path = dest / name
    req = urllib.request.Request(c["url"], headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    if path.stat().st_size < 50_000:  # truncated / placeholder response
        path.unlink()
        raise ValueError("suspiciously small download")
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dest", type=Path, default=DEST)
    ap.add_argument("--topics", help="comma-separated search terms (overrides defaults)")
    ap.add_argument("--add", type=int, default=8, help="how many new images to fetch")
    ap.add_argument("--keep", type=int, default=40, help="prune folder to this many, oldest first")
    ap.add_argument("--min-width", type=int, default=3000)
    ap.add_argument("--min-ratio", type=float, default=1.2, help="w/h; 1.2 keeps it landscape-ish")
    ap.add_argument("--sources", help="comma-separated subset of: aic,cma,met")
    ap.add_argument("--list", action="store_true", help="list current folder and exit")
    args = ap.parse_args()

    args.dest.mkdir(parents=True, exist_ok=True)
    existing = sorted(args.dest.glob("*.jpg"), key=lambda p: p.stat().st_mtime)

    if args.list:
        for p in existing:
            print(f"{p.stat().st_size // 1024:>6} KB  {p.name}")
        print(f"\n{len(existing)} images in {args.dest}")
        return 0

    have = {"-".join(p.name.split("-")[:2]) for p in existing if "-" in p.name}
    topics = [t.strip() for t in args.topics.split(",")] if args.topics else TOPICS
    sources = SOURCES
    if args.sources:
        pick = {s.strip() for s in args.sources.split(",")}
        sources = [(fn, n) for fn, n in SOURCES if fn.__name__ in pick]

    pool = []
    for topic in topics:
        for fn, limit in sources:
            try:
                pool += [c for c in fn(topic, limit) if wanted(c, args.min_width, args.min_ratio)]
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
                print(f"  ! {fn.__name__} '{topic}': {e}", file=sys.stderr)

    fresh = [c for c in pool if f"{c['source']}-{c['id']}" not in have]
    random.shuffle(fresh)
    by_src = {}
    for c in pool:
        by_src[c["source"]] = by_src.get(c["source"], 0) + 1
    breakdown = ", ".join(f"{k}:{v}" for k, v in sorted(by_src.items())) or "none"
    print(f"{len(pool)} candidates pass filters ({breakdown}), {len(fresh)} not already on disk")

    added = 0
    for c in fresh:
        if added >= args.add:
            break
        try:
            fetch(c, args.dest)
            added += 1
            print(f"  + [{c['source']} {c['width']}x{c['height']}] {c.get('artist') or '?'} — {c.get('title')}")
        except Exception as e:
            print(f"  ! {c['source']}-{c['id']}: {e}", file=sys.stderr)

    files = sorted(args.dest.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    for p in files[: max(0, len(files) - args.keep)]:
        p.unlink()
        print(f"  - pruned {p.name}")

    print(f"\nAdded {added}. Folder now holds {len(list(args.dest.glob('*.jpg')))} images at {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
