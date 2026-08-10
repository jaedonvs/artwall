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
import html
import json
import os
import random
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

# Three folders. The weekly job fills the backlog (all the network work); the
# daily job just moves one file backlog -> live -> archive. LIVE is what macOS
# points at and holds exactly one image, which is what keeps the desktop and
# lock screen showing the same picture — they shuffle independently, so a
# one-item folder is the only choice both can land on.
HOME = Path.home() / "Pictures" / "artwall"
LIVE = Path.home() / "Pictures" / "Wallpapers"
STORE = ".artwall.json"  # metadata store, lives in HOME
GALLERY = "GALLERY.md"  # human-readable index, regenerated every run

MUSEUM = {
    "aic": "Art Institute of Chicago",
    "cma": "Cleveland Museum of Art",
    "met": "The Metropolitan Museum of Art",
}

# Captioning is the one feature with a dependency. Pillow is optional: without
# it the images still download, they just don't get a caption burned in.
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

SCREEN_FALLBACK = (2560, 1440)

FONT_REGULAR = "/System/Library/Fonts/HelveticaNeue.ttc"
FONT_FALLBACK = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

UA = "artwall/1.0 (personal wallpaper fetcher; stdlib urllib)"
# The Art Institute's IIIF server 403s without this identifying header. They ask
# for a contact channel; set ARTWALL_CONTACT to your own if you'd rather they
# reach you directly about usage.
CONTACT = os.environ.get("ARTWALL_CONTACT", "https://github.com/jaedonvs/artwall")
HEADERS = {"User-Agent": UA, "AIC-User-Agent": f"artwall ({CONTACT})"}

MET = "https://collectionapi.metmuseum.org/public/collection/v1"
WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# Plain-English glossary for the jargon museum metadata is full of. Matched as
# substrings against a work's style, medium and origin, so a beginner isn't left
# guessing what "mezzotint" or "ōban" means. Longest match wins per work.
GLOSSARY = {
    "ukiyo-e": "Japanese woodblock prints of the “floating world” — theatre, city life and landscape, mass-produced for ordinary buyers in Edo-era Japan.",
    "woodblock": "Printed by carving a design into wood, inking the raised surface and pressing paper onto it. A separate block is cut for each colour.",
    "mezzotint": "The whole metal plate is roughened so it would print solid black, then smoothed back where light is wanted. Gives unusually deep, velvety darks.",
    "aquatint": "An etching technique using powdered resin to bite tonal areas rather than lines, producing washes that look like watercolour.",
    "etching": "Lines are drawn through a waxy coating on a metal plate, then acid bites them in. The plate is inked and printed.",
    "engraving": "Lines cut directly into metal with a hand tool. Sharper and more deliberate than etching, since there's no acid and no undoing.",
    "lithograph": "Drawn in grease on stone; the stone is wetted so ink sticks only to the drawing. Prints look close to the artist's own hand.",
    "gouache": "Watercolour made opaque with added white, so it sits flat and solid instead of translucent.",
    "watercolor": "Pigment in water on paper, built up in transparent layers. The paper's whiteness supplies the light, so highlights are areas left bare.",
    "oil on canvas": "Pigment bound in oil. It dries slowly, which lets colours be blended wet and reworked over weeks — the reason oil dominates Western painting.",
    "oil on fabric": "Pigment bound in oil. It dries slowly, which lets colours be blended wet and reworked over weeks — the reason oil dominates Western painting.",
    "graphite": "Pencil. Usually a working drawing rather than a finished piece — a chance to see an artist thinking.",
    "folding screen": "A room divider painted across hinged panels, read right to left. Made to be seen in changing light, not hung flat.",
    "albumen": "An early photographic print on paper coated with egg white, giving the warm brown tone typical of 19th-century photographs.",
    "impressionism": "1870s France: painting outdoors, fast, chasing changing light. Visible brushstrokes and everyday subjects, which critics first took as unfinished.",
    "post-impressionism": "What came after the Impressionists — Cézanne, Van Gogh, Gauguin — keeping the bright colour but pushing toward structure, emotion and pattern.",
    "hudson river school": "19th-century American landscape painters treating wilderness as something close to sacred, with vast views and glowing light.",
    "art nouveau": "Around 1900: whiplash curves, plant forms and flat colour, applied to posters, glass and buildings alike. Deliberately modern and decorative.",
    "arts and crafts": "A Victorian reaction against factory goods, arguing for handmade work and honest materials. William Morris was its loudest voice.",
    "romanticism": "Early 19th century: feeling over reason. Storms, ruins and the sublime — nature as overwhelming rather than orderly.",
    "realism": "Mid-19th century: ordinary people and unglamorous work painted at the scale once reserved for gods and generals.",
    "baroque": "17th century: strong diagonals, theatrical light and dark, and a lot of drama aimed straight at the viewer.",
    "still life": "Arranged objects — food, flowers, vessels. Often about abundance, and about decay: the fruit is always a little too ripe.",
    "edo period": "Japan, 1615–1868. A long closed-off peace in which a wealthy merchant class drove a boom in prints, theatre and popular art.",
    "oban": "A standard Japanese print size, roughly 25 × 38 cm — the format most famous ukiyo-e landscapes were made in.",
}

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


def clean(s, maxlen=None):
    """Museum prose arrives as HTML; artist fields arrive with hard newlines."""
    if not s:
        return None
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(s)))
    s = re.sub(r"\s+", " ", s).strip()
    if maxlen and len(s) > maxlen:
        s = s[:maxlen].rsplit(" ", 1)[0] + "…"
    return s or None


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


def safe_url(url):
    """Percent-encode stray characters in the path.

    Some Met filenames contain literal spaces ('figure 107R1_24Z.jpg'), which
    urllib rejects outright as InvalidURL.
    """
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(p.path, safe="/%")))


def probe_dims(url, timeout=30):
    """Read just enough of a remote JPEG to learn its dimensions."""
    req = urllib.request.Request(safe_url(url), headers={**HEADERS, "Range": "bytes=0-131071"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return jpeg_dims(r.read())
    except Exception:  # one unreadable candidate must never kill a run
        return None


# ---------------------------------------------------------------------- sources


def aic(topic, limit):
    """Art Institute of Chicago. Search returns full master dimensions."""
    q = urllib.parse.urlencode(
        {
            "q": topic,
            "query[term][is_public_domain]": "true",
            "fields": "id,title,artist_title,artist_display,date_display,medium_display,"
            "style_title,place_of_origin,short_description,description,image_id,thumbnail",
            "limit": limit,
        }
    )
    for a in get_json(f"https://api.artic.edu/api/v1/artworks/search?{q}").get("data", []):
        t, img = a.get("thumbnail") or {}, a.get("image_id")
        w, h = t.get("width"), t.get("height")
        if not (img and w and h):
            continue
        yield {
            "source": "aic",
            "id": a["id"],
            # Resolved to a real IIIF tier at download time; see aic_best_url.
            "image_id": img,
            "title": a.get("title"),
            "artist": a.get("artist_title"),
            "artist_full": clean(a.get("artist_display")),
            "date": clean(a.get("date_display")),
            "medium": clean(a.get("medium_display")),
            "style": clean(a.get("style_title")),
            "origin": clean(a.get("place_of_origin")),
            "blurb": clean(a.get("short_description")) or clean(a.get("description"), 700),
            "page": f"https://www.artic.edu/artworks/{a['id']}",
            "width": w,
            "height": h,
            "url": f"https://www.artic.edu/iiif/2/{img}/full/3000,/0/default.jpg",
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
        culture = a.get("culture") or []
        yield {
            "source": "cma",
            "id": a.get("id"),
            "title": a.get("title"),
            "artist": (creators[0].get("description") or "").split("(")[0].strip(),
            "artist_full": clean(creators[0].get("description")),
            "date": clean(a.get("creation_date")),
            "medium": clean(a.get("technique")),
            "style": clean(a.get("type")),
            "origin": clean(", ".join(culture) if isinstance(culture, list) else culture),
            "blurb": clean(a.get("wall_description")) or clean(a.get("description"), 700),
            "page": a.get("url"),
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
        except Exception:
            continue
        url = o.get("primaryImage")
        if not url or not o.get("isPublicDomain"):
            continue
        dims = probe_dims(url)
        if not dims:
            continue
        bio = clean(o.get("artistDisplayBio"))
        name = clean(o.get("artistDisplayName"))
        yield {
            "source": "met",
            "id": oid,
            "title": o.get("title"),
            "artist": name,
            "artist_full": " — ".join(x for x in (name, bio) if x) or None,
            "date": clean(o.get("objectDate")),
            "medium": clean(o.get("medium")),
            "style": clean(o.get("classification")),
            "origin": clean(o.get("culture")) or clean(o.get("period")),
            # The Met's API carries no prose description; credit line is the
            # closest thing to context it offers.
            "blurb": clean(o.get("creditLine")),
            "page": o.get("objectURL"),
            "width": dims[0],
            "height": dims[1],
            "url": url,
        }


SOURCES = [(aic, 40), (cma, 40), (met, 10)]


# ------------------------------------------------------------------------- main


def _font(size):
    for path in (FONT_REGULAR, FONT_FALLBACK):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, maxw):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= maxw or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def detect_screen():
    """Main display resolution in pixels, for composing at exact screen size."""
    try:
        out = os.popen("system_profiler SPDisplaysDataType 2>/dev/null").read()
        m = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return SCREEN_FALLBACK


def compose(path, e, screen):
    """Rebuild the image as a museum wall label: art, then caption beside it.

    Composed at exactly the screen resolution, so macOS neither scales nor crops
    — which also means nothing ever overlaps the artwork. The caption goes in
    the margin the art already wasn't using: a column at the side when the work
    is narrower than the screen, a band underneath when it's wider.
    """
    art = Image.open(path)
    if art.mode != "RGB":
        art = art.convert("RGB")
    SW, SH = screen
    pad = SW // 47

    side = (art.width / art.height) < (SW / SH)
    if side:
        col = int(SW * 0.24)
        art_box = (SW - col - pad * 2, SH - pad * 2)
    else:
        band = int(SH * 0.22)
        art_box = (SW - pad * 2, SH - band - pad * 2)

    # Ambient backdrop: the art itself, blown up, blurred and dimmed.
    canvas = Image.new("RGB", (SW, SH))
    bg = art.resize((SW, SH), Image.LANCZOS).filter(ImageFilter.GaussianBlur(60))
    canvas.paste(Image.blend(bg, Image.new("RGB", (SW, SH), (10, 10, 12)), 0.66))

    a = art.copy()
    a.thumbnail(art_box, Image.LANCZOS)
    ax = pad if side else (SW - a.width) // 2
    ay = (SH - a.height) // 2 if side else pad
    canvas.paste(a, (ax, ay))

    d = ImageDraw.Draw(canvas)
    if side:
        x, y = ax + a.width + pad, ay + pad // 8
        maxw = SW - x - pad
    else:
        x, y = pad * 2, ay + a.height + pad
        maxw = SW - pad * 4

    f_artist, f_title = _font(SW // 67), _font(SW // 91)
    f_facts, f_blurb, f_head = _font(SW // 122), _font(SW // 128), _font(SW // 155)
    bottom = SH - pad

    def emit(text, font, colour, maxlines, lead):
        """Draw wrapped text, stopping at the bottom margin. True if it all fit."""
        nonlocal y
        lines = _wrap(d, text, font, maxw)
        for i, line in enumerate(lines[:maxlines]):
            if y + lead > bottom:
                return False
            d.text((x, y), line, font=font, fill=colour)
            y += lead
        return len(lines) <= maxlines

    def heading(text):
        nonlocal y
        if y + f_head.size * 2.4 > bottom:
            return False
        y += int(pad * 0.45)
        d.text((x, y), text.upper(), font=f_head, fill=(132, 132, 142))
        y += int(f_head.size * 1.7)
        return True

    emit(e.get("artist") or "Unknown", f_artist, (255, 255, 255), 2, int(f_artist.size * 1.22))
    y += pad // 6
    if e.get("title"):
        emit(e["title"], f_title, (238, 238, 240), 3 if side else 1, int(f_title.size * 1.3))
    y += pad // 4
    if facts(e):
        emit(facts(e), f_facts, (168, 168, 176), 4 if side else 1, int(f_facts.size * 1.35))

    if not side:  # bottom band: only room for the description itself
        if e.get("blurb"):
            y += pad // 3
            emit(e["blurb"], f_blurb, (196, 196, 202), 3, int(f_blurb.size * 1.45))
        canvas.save(path, "JPEG", quality=90)
        return

    lead = int(f_blurb.size * 1.45)
    if e.get("blurb") and heading("About this work"):
        emit(e["blurb"], f_blurb, (208, 208, 214), 99, lead)
    if e.get("artist_bio") and heading("About the artist"):
        emit(e["artist_bio"], f_blurb, (196, 196, 202), 99, lead)
    if e.get("terms") and heading("Terms"):
        for t in e["terms"]:
            if not emit(t, f_blurb, (178, 178, 186), 99, lead):
                break
            y += pad // 8

    canvas.save(path, "JPEG", quality=90)


def load_store(home):
    try:
        return json.loads((home / STORE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_store(home, store):
    home.mkdir(parents=True, exist_ok=True)
    (home / STORE).write_text(json.dumps(store, indent=1, ensure_ascii=False))


def dirs(home):
    """(backlog, archive), created on demand."""
    b, a = home / "backlog", home / "archive"
    for d in (b, a):
        d.mkdir(parents=True, exist_ok=True)
    return b, a


def migrate(home, live_dir):
    """Move a pre-three-folder store into HOME and label existing states."""
    old = live_dir / STORE
    if (home / STORE).exists() or not old.exists():
        return
    store = json.loads(old.read_text())
    on_disk = {p.name for p in live_dir.glob("*.jpg")}
    for e in store.values():
        e["state"] = "live" if e.get("filename") in on_disk else "gone"
    save_store(home, store)
    old.unlink()
    (live_dir / GALLERY).unlink(missing_ok=True)
    print(f"Migrated {len(store)} catalogued works into {home}")


def rotate(home, live_dir, store):
    """Retire the live image to the archive and promote one from the backlog."""
    backlog, archive = dirs(home)
    live_dir.mkdir(parents=True, exist_ok=True)
    by_name = {e.get("filename"): e for e in store.values()}

    for p in sorted(live_dir.glob("*.jpg")):
        shutil.move(str(p), str(archive / p.name))
        if p.name in by_name:
            by_name[p.name]["state"] = "archive"
        print(f"  → archived {p.name}")

    queued = sorted(backlog.glob("*.jpg"))
    if not queued:
        return None
    pick = random.choice(queued)
    shutil.move(str(pick), str(live_dir / pick.name))
    if pick.name in by_name:
        by_name[pick.name]["state"] = "live"
    return pick.name


def facts(c):
    """The one-line tombstone: date, medium, origin, museum."""
    bits = [c.get("date"), c.get("medium"), c.get("origin"), MUSEUM.get(c.get("source"))]
    return " · ".join(b for b in bits if b)


def write_gallery(home, store):
    """Regenerate the human-readable index, grouped by which folder each is in."""
    groups = {"live": [], "backlog": [], "archive": [], "gone": []}
    for e in store.values():
        groups.get(e.get("state", "gone"), groups["gone"]).append(e)
    for k in ("backlog", "archive", "gone"):
        groups[k].sort(key=lambda e: (e.get("artist") or "~", e.get("title") or ""))
    seen = len(groups["archive"]) + len(groups["gone"])

    out = [
        "# Wallpapers",
        "",
        f"*{len(groups['backlog'])} queued, {seen} already shown · "
        f"regenerated {date.today().isoformat()}*",
        "",
        "---",
        "",
    ]

    def full(e):
        block = [f"## {e.get('artist') or 'Unknown'} — {e.get('title') or 'Untitled'}", ""]
        if e.get("artist_full"):
            block.append(f"**{e['artist_full']}**  ")
        if facts(e):
            block.append(f"{facts(e)}  ")
        block += [f"`{e.get('filename', '')}` · {e.get('width')}×{e.get('height')}", ""]
        if e.get("blurb"):
            block += [e["blurb"], ""]
        if e.get("page"):
            block += [f"[View at the museum]({e['page']})", ""]
        return block + ["---", ""]

    def brief(e):
        bits = [f"**{e.get('artist') or 'Unknown'} — {e.get('title') or 'Untitled'}**"]
        if facts(e):
            bits.append(f"  \n{facts(e)}")
        if e.get("blurb"):
            bits.append(f"  \n{clean(e['blurb'], 400)}")
        if e.get("page"):
            bits.append(f"  \n[View at the museum]({e['page']})")
        return ["".join(bits), ""]

    if groups["live"]:
        out += ["# Now showing", ""]
        for e in groups["live"]:
            out += full(e)

    if groups["backlog"]:
        out += ["# Up next", "", f"{len(groups['backlog'])} waiting in the backlog.", ""]
        for e in groups["backlog"]:
            out += brief(e)
        out += ["---", ""]

    if groups["archive"] or groups["gone"]:
        out += [
            "# Previously shown",
            "",
            "Kept so the record survives — and so the same work is never fetched twice.",
            "",
        ]
        for e in groups["archive"] + groups["gone"]:
            out += brief(e)

    (home / GALLERY).write_text("\n".join(out))


def _wiki_try(title, sentences):
    """One Wikipedia summary lookup. None if missing or a disambiguation page."""
    try:
        d = get_json(WIKI + urllib.parse.quote(title.replace(" ", "_")), timeout=15)
    except Exception:
        return None
    if d.get("type", "").endswith(("not_found", "disambiguation")):
        return None
    text = clean(d.get("extract"))
    # Common-name artists land on a disambiguation page that the API doesn't
    # always type as one — "John Martin may refer to:" is worse than no bio.
    if not text or re.search(r"\bmay refer to\b|\bmay also refer to\b", text, re.I):
        return None
    return " ".join(re.split(r"(?<=[.!?]) +", text)[:sentences])


def wiki_bio(name, cache, sentences=2):
    """Beginner-level context on the artist, from Wikipedia's summary endpoint."""
    if not name:
        return None
    if name in cache:
        return cache[name]
    bio = None
    for title in (name, f"{name} (painter)", f"{name} (artist)"):
        bio = _wiki_try(title, sentences)
        if bio:
            break
    cache[name] = bio
    return bio


def _term_label(term):
    """Display form of a glossary key. str.title() gets both of these wrong:
    'arts and crafts' -> 'Arts And Crafts', 'ukiyo-e' -> 'Ukiyo-E'."""
    small = {"and", "on", "of", "the", "in", "a"}
    words = [w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(term.split())]
    return " ".join(words)


def glossary_for(e, limit=2):
    """Explain the jargon in this work's style/medium, longest match first."""
    hay = " ".join(
        str(e.get(k) or "").lower() for k in ("style", "medium", "origin", "title")
    )
    hits = [(term, defn) for term, defn in GLOSSARY.items() if term in hay]
    hits.sort(key=lambda t: -len(t[0]))
    out, used = [], set()
    for term, defn in hits:
        if any(term in u or u in term for u in used):
            continue  # don't explain "woodblock" right after "ukiyo-e"
        used.add(term)
        out.append(f"{_term_label(term)} — {defn}")
        if len(out) >= limit:
            break
    return out


def enrich(c, cache):
    """Attach beginner-facing context: artist bio and a jargon glossary."""
    c["artist_bio"] = wiki_bio(c.get("artist"), cache)
    c["terms"] = glossary_for(c)
    return c


def wanted(c, min_width, min_ratio):
    return c["width"] >= min_width and c["width"] / c["height"] >= min_ratio


MAX_PX = 6000  # beyond this, files get large for no visible gain on any display


def aic_best_url(image_id, cap=MAX_PX):
    """Pick the largest IIIF tier at or below `cap`.

    The Art Institute serves any width up to 3000, but above that ONLY the exact
    tier widths its pyramid advertises — an off-tier request like 6000 silently
    clamps to 3000. info.json lists the real tiers, so ask for one of those.
    """
    base = f"https://www.artic.edu/iiif/2/{image_id}"
    try:
        sizes = get_json(f"{base}/info.json").get("sizes") or []
        widths = sorted(s["width"] for s in sizes if s.get("width"))
    except Exception:
        widths = []
    ok = [w for w in widths if w <= cap]
    best = max(ok) if ok else min(cap, 3000)
    return f"{base}/full/{best},/0/default.jpg"


def fetch(c, dest, min_width=0, screen=None):
    name = f"{c['source']}-{c['id']}-{slug(c.get('artist'))}-{slug(c.get('title'))}.jpg"
    path = dest / name
    url = aic_best_url(c["image_id"]) if c.get("image_id") else c["url"]
    req = urllib.request.Request(safe_url(url), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    if path.stat().st_size < 50_000:  # truncated / placeholder response
        path.unlink()
        raise ValueError("suspiciously small download")

    # Catalogue dimensions can be wrong or stale, and IIIF may serve less than
    # asked. Trust the bytes on disk, not the API.
    if HAVE_PIL:
        w, h = Image.open(path).size
        c["width"], c["height"] = w, h
        if w < min_width:
            path.unlink()
            raise ValueError(f"served {w}px, below --min-width {min_width}")
        if screen:
            compose(path, c, screen)
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--home", type=Path, default=HOME, help="holds backlog/, archive/, catalogue")
    ap.add_argument("--live", type=Path, default=LIVE, help="folder macOS points at (one image)")
    ap.add_argument("--topics", help="comma-separated search terms (overrides defaults)")
    ap.add_argument("--add", type=int, default=7, help="how many to fetch into the backlog")
    ap.add_argument("--rotate", action="store_true", help="daily: archive the live image, promote one from the backlog")
    ap.add_argument("--min-width", type=int, default=3000)
    ap.add_argument("--min-ratio", type=float, default=1.2, help="w/h; 1.2 keeps it landscape-ish")
    ap.add_argument("--sources", help="comma-separated subset of: aic,cma,met")
    ap.add_argument("--list", action="store_true", help="show status across all three folders")
    ap.add_argument("--raw", action="store_true", help="save the bare artwork, no label")
    ap.add_argument("--screen", help="compose for this size, e.g. 2560x1440 (default: detected)")
    ap.add_argument(
        "--recompose",
        action="store_true",
        help="re-download and rebuild every catalogued image, then exit",
    )
    args = ap.parse_args()

    screen = None
    if not args.raw:
        if not HAVE_PIL:
            print("  ! Pillow missing — saving raw art (pip3 install --user Pillow)", file=sys.stderr)
        elif args.screen:
            screen = tuple(int(v) for v in args.screen.lower().split("x"))
        else:
            screen = detect_screen()

    migrate(args.home, args.live)
    backlog, archive = dirs(args.home)
    args.live.mkdir(parents=True, exist_ok=True)
    store = load_store(args.home)

    if args.list:
        for label, d in (("live", args.live), ("backlog", backlog), ("archive", archive)):
            files = sorted(d.glob("*.jpg"))
            mb = sum(p.stat().st_size for p in files) / 1024 / 1024
            print(f"  {label:<8} {len(files):>3} image(s)  {mb:5.1f} MB  {d}")
            if label == "live":
                for p in files:
                    print(f"           {p.name}")
        print(f"\n  catalogued: {len(store)} works")
        return 0

    if args.rotate:
        shown = rotate(args.home, args.live, store)
        if shown is None:
            # Backlog dry: fetch one now so the desktop never goes stale, and
            # say so loudly — it means the weekly fill didn't run.
            print("  ! backlog empty — fetching one directly", file=sys.stderr)
            args.add, args.rotate = 1, False
        else:
            e = next((v for v in store.values() if v.get("filename") == shown), {})
            print(f"\n  now showing: {e.get('artist') or '?'} — {e.get('title') or shown}")
            print(f"  {len(list(backlog.glob('*.jpg')))} left in backlog")
            save_store(args.home, store)
            write_gallery(args.home, store)
            return 0

    if args.recompose:
        # Composing overwrites the file, so a rebuild has to start from the
        # source again rather than re-processing an already-composed image.
        done, bios = 0, {}
        print(f"Rebuilding at {screen[0]}x{screen[1]}…" if screen else "Rebuilding raw…")
        where = {"live": args.live, "backlog": backlog, "archive": archive}
        for key, e in store.items():
            d = where.get(e.get("state"))
            if not d or not (d / (e.get("filename") or "")).exists():
                continue  # no file to rebuild
            try:
                # Key presence, not truthiness: a genuinely bio-less artist
                # shouldn't be re-looked-up on every rebuild.
                if "artist_bio" not in e or "terms" not in e:
                    enrich(e, bios)  # backfill context onto pre-existing entries
                path = fetch(e, d, args.min_width, screen)
                e["filename"], e["composed"] = path.name, bool(screen)
                done += 1
                print(f"  ✓ {e.get('artist')} — {e.get('title')}")
            except Exception as exc:
                print(f"  ! {key}: {exc}", file=sys.stderr)
        save_store(args.home, store)
        write_gallery(args.home, store)
        print(f"\nRebuilt {done} image(s).")
        return 0

    # Dedup against everything ever catalogued, in any folder — the live folder
    # holds one image and is no record of what's been seen.
    have = set(store)
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
            except Exception as e:  # a flaky source shouldn't sink the other two
                print(f"  ! {fn.__name__} '{topic}': {e}", file=sys.stderr)

    fresh = [c for c in pool if f"{c['source']}-{c['id']}" not in have]
    random.shuffle(fresh)
    by_src = {}
    for c in pool:
        by_src[c["source"]] = by_src.get(c["source"], 0) + 1
    breakdown = ", ".join(f"{k}:{v}" for k, v in sorted(by_src.items())) or "none"
    print(f"{len(pool)} candidates pass filters ({breakdown}), {len(fresh)} not yet seen")

    added, bios = 0, {}
    for c in fresh:
        if added >= args.add:
            break
        try:
            enrich(c, bios)
            path = fetch(c, backlog, args.min_width, screen)
            added += 1
            store[f"{c['source']}-{c['id']}"] = {
                **c,
                "filename": path.name,
                "composed": bool(screen),
                "state": "backlog",
            }
            print(f"\n  + {c.get('artist') or '?'} — {c.get('title')}")
            print(f"    {facts(c)} · {c['width']}×{c['height']}")
            if c.get("blurb"):
                print(f"    {clean(c['blurb'], 220)}")
        except Exception as e:
            print(f"  ! {c['source']}-{c['id']}: {e}", file=sys.stderr)

    # If the backlog ran dry, promote immediately so the desktop isn't left stale.
    if added and not list(args.live.glob("*.jpg")):
        rotate(args.home, args.live, store)

    # Store entries outlive their images on purpose: they're the dedup memory
    # (so a work is never fetched twice) and the GALLERY history.
    save_store(args.home, store)
    write_gallery(args.home, store)

    queued = len(list(backlog.glob("*.jpg")))
    described = sum(1 for e in store.values() if e.get("blurb"))
    print(f"\nAdded {added} to the backlog — {queued} queued, {len(store)} catalogued")
    print(f"Wrote {args.home / GALLERY} ({described} with a written description)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
