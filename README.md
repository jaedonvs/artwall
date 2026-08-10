# artwall

Keeps `~/Pictures/Wallpapers` topped up with high-resolution public-domain art,
so macOS's built-in folder rotation always has something new to show.

Stdlib-only Python 3 — no `requests`, no venv, no dependencies to break a
scheduled run.

## Sources

| Source | Key? | Delivered resolution | Dimensions known before download? |
|---|---|---|---|
| Art Institute of Chicago | no | largest IIIF tier ≤ 6000px | claimed in search, verified on disk |
| Cleveland Museum of Art | no | 3400px (`print` JPEG) | yes, in search results |
| Metropolitan Museum of Art | no | ~4000px typical | no — see below |

All three publish public-domain works and are filtered on their own
`is_public_domain` / `cc0` flags.

The Met's API never reports image dimensions, so orientation filtering needs a
ranged `Range: bytes=0-131071` read of each candidate and a hand-rolled JPEG SOF
parser (`jpeg_dims`). That costs two requests per candidate instead of zero,
which is why the Met's per-topic limit is 10 against the others' 40.

The Art Institute's IIIF server has a trap: it serves any width **up to 3000**,
but above that only the exact tier widths its image pyramid advertises. An
off-tier request like `6000,` silently returns 3000px rather than erroring, so a
naive `min(master_width, 6000)` caps every large work at 3000. `aic_best_url`
reads `info.json` and picks the largest advertised tier ≤ 6000.

Because catalogue dimensions can also be stale or rounded — one work reported
8000×6000 and delivered 3000×2482 — every download is re-measured from the bytes
on disk. The store records what actually arrived, and anything below
`--min-width` is deleted rather than kept.

### Why not Artvee

Artvee is the nicest browsing surface for this material, but its `robots.txt`
runs the Ultimate AI Block List, which names `Anthropic`, `Claude`, `AI Agent`,
`Agentic` and friends with `Disallow: /` while allowing every other bot. That is
a deliberate opt-out, so this tool doesn't touch it.

No loss in practice: Artvee is an *index* over these same institutions, and
going direct to their APIs returns higher-resolution masters than Artvee's free
tier serves. Browsing Artvee yourself is unaffected — drop anything you find
there into `~/Pictures/Wallpapers` and it joins the rotation.

## Descriptions

Every fetched work gets a caption panel burned into the **bottom-right corner**
of the image itself — artist, title, date, medium, museum, and the opening of
the description. Since macOS offers no way to ask which wallpaper is currently
displayed, putting the text in the picture is the only way to know what you're
looking at without going hunting.

Font sizes scale with image width, so the caption lands at roughly the same
apparent size once macOS scales the picture to your display — otherwise a
6000px master would render its text at half the size of a 3000px one on the
same screen.

Captioning is the one feature with a dependency (Pillow). It degrades
gracefully: without Pillow the images still download, just uncaptioned.

```bash
./artwall.py --no-caption     # leave images untouched
./artwall.py --recaption      # caption already-downloaded images, then exit
```

`--recaption` is idempotent — it skips anything already marked `captioned` in
the store, so it won't double-stamp.

Each run also writes two files alongside the images:

- **`GALLERY.md`** — a readable index of everything currently in rotation:
  artist and life dates, year, medium, origin, museum, the museum's own written
  description where one exists, and a link to the work's page.
- **`.artwall.json`** — the hidden metadata store `GALLERY.md` is generated
  from. Delete it and you lose descriptions, not images.

Prose coverage varies by institution, and the tool is explicit about which
entries have it:

| Source | Written description |
|---|---|
| Cleveland | usually — `wall_description` is the literal museum wall label |
| Art Institute | sometimes — `short_description`, often absent for prints |
| The Met | never — its API carries no prose, so entries are facts plus credit line |

Every entry always gets the structured facts and a museum link regardless.

macOS gives no way to ask which wallpaper is currently displayed — the old
AppleScript hook returns `missing value` under folder rotation, and the Sonoma
private store holds no image paths. So matching a picture to its entry goes via
the filename, which carries artist and title; `GALLERY.md` lists it under each
work.

Images you add by hand are listed under **Not catalogued** rather than silently
omitted.

## Install

Runs are manual by default:

```bash
./artwall.py
```

To schedule a weekly top-up instead, `./install.sh` installs a launchd agent for
Mondays at 09:00, logging to `~/Library/Logs/artwall.log`. Remove it with:

```bash
launchctl bootout gui/$(id -u)/com.jaedon.artwall
rm ~/Library/LaunchAgents/com.jaedon.artwall.plist
```

Either way, one manual step is needed once — macOS moved wallpaper state into a
private store in Sonoma, so this can't be scripted reliably:

> System Settings → Wallpaper → scroll to the bottom → **Add Folder** →
> `~/Pictures/Wallpapers` → set *Change picture: Every day* + **Random order**

## Usage

```bash
./artwall.py                                       # top up with default topics
./artwall.py --topics "bauhaus,constructivism" --add 12
./artwall.py --sources met --add 5                 # one source only
./artwall.py --min-width 3800                      # for a 5K display
./artwall.py --list
```

| Flag | Default | Notes |
|---|---|---|
| `--add` | 5 | new images to fetch this run |
| `--keep` | 40 | prune folder to this many, oldest first |
| `--min-width` | 3000 | raise to 3800 for a 5K Studio Display |
| `--min-ratio` | 1.2 | width/height; keeps things landscape-ish |
| `--topics` | see `TOPICS` | comma-separated full-text search terms |
| `--sources` | all | subset of `aic,cma,met` |
| `--no-caption` | off | skip burning the caption into the image |
| `--recaption` | — | caption existing images that lack one, then exit |

The Art Institute's IIIF server returns 403 without an `AIC-User-Agent` header
carrying a contact channel. It defaults to this repo's URL; set
`ARTWALL_CONTACT` if you'd rather they could reach you directly:

```bash
export ARTWALL_CONTACT="you@example.com"
```

## Tuning

Taste lives in the `TOPICS` list at the top of `artwall.py`. Searches are
full-text against each museum's catalogue, so terms can be movements
(`post-impressionism`), media (`japanese woodblock landscape`), subjects
(`still life flowers`), or artist names.

Two known rough edges:

- Full-text search occasionally returns a *photograph of* an object rather than
  a painting — a Thorne miniature room turned up under `still life`. Narrower
  topics fix it.
- At `--min-width 3800` Cleveland drops out almost entirely, since its largest
  JPEG variant is 3400px. AIC's IIIF masters carry the load above that.

Filenames are `{source}-{id}-{artist}-{title}.jpg`; the `{source}-{id}` prefix
is what dedupes against what's already on disk, so don't rename them if you want
re-runs to skip what you already have.
