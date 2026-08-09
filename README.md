# artwall

Keeps `~/Pictures/Wallpapers` topped up with high-resolution public-domain art,
so macOS's built-in folder rotation always has something new to show.

Stdlib-only Python 3 — no `requests`, no venv, no dependencies to break a
scheduled run.

## Sources

| Source | Key? | Max resolution | Dimensions known before download? |
|---|---|---|---|
| Art Institute of Chicago | no | ~18000px via IIIF | yes, in search results |
| Cleveland Museum of Art | no | 3400px (`print` JPEG) | yes, in search results |
| Metropolitan Museum of Art | no | ~4000px typical | no — see below |

All three publish public-domain works and are filtered on their own
`is_public_domain` / `cc0` flags.

The Met's API never reports image dimensions, so orientation filtering needs a
ranged `Range: bytes=0-131071` read of each candidate and a hand-rolled JPEG SOF
parser (`jpeg_dims`). That costs two requests per candidate instead of zero,
which is why the Met's per-topic limit is 10 against the others' 40.

### Why not Artvee

Artvee is the nicest browsing surface for this material, but its `robots.txt`
runs the Ultimate AI Block List, which names `Anthropic`, `Claude`, `AI Agent`,
`Agentic` and friends with `Disallow: /` while allowing every other bot. That is
a deliberate opt-out, so this tool doesn't touch it.

No loss in practice: Artvee is an *index* over these same institutions, and
going direct to their APIs returns higher-resolution masters than Artvee's free
tier serves. Browsing Artvee yourself is unaffected — drop anything you find
there into `~/Pictures/Wallpapers` and it joins the rotation.

## Install

```bash
./install.sh
```

Installs a launchd agent that runs Mondays at 09:00, adds 8 images, and prunes
the folder back to 40 (oldest first). Logs to `~/Library/Logs/artwall.log`.

Then, once, by hand — macOS moved wallpaper state into a private store in
Sonoma, so this can't be scripted reliably:

> System Settings → Wallpaper → scroll to the bottom → **Add Folder** →
> `~/Pictures/Wallpapers` → set *Change picture: Every hour* + **Random order**

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
| `--add` | 8 | new images to fetch this run |
| `--keep` | 40 | prune folder to this many, oldest first |
| `--min-width` | 3000 | raise to 3800 for a 5K Studio Display |
| `--min-ratio` | 1.2 | width/height; keeps things landscape-ish |
| `--topics` | see `TOPICS` | comma-separated full-text search terms |
| `--sources` | all | subset of `aic,cma,met` |

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
