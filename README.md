# artwall

Puts a different public-domain artwork on your Mac desktop every morning,
captioned like a museum wall label.

Three folders, two jobs. A **weekly** job does all the network work and stocks a
backlog; a **daily** job just moves one file. Nothing fetches on the critical
path, so a slow museum API can never leave you without a wallpaper.

```
~/Pictures/artwall/backlog/   queued, ready to show
~/Pictures/Wallpapers/        exactly one image — macOS points here
~/Pictures/artwall/archive/   everything already shown
```

The live folder holds exactly **one** image on purpose. macOS shuffles the
desktop and lock screen independently, so a one-item folder is the only choice
both can land on — see [Matching the lock screen](#matching-the-lock-screen).

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
there into `~/Pictures/artwall/backlog/` and it takes its turn like any other.
Hand-added images rotate normally; they just have no catalogue entry, so they
show up unlabelled and without a description.

## Descriptions

Each wallpaper is composed as a **museum wall label**: the artwork, and beside
it the artist, title, date, medium, museum, and the museum's own description.
Since macOS offers no way to ask which wallpaper is currently displayed, putting
the text in the picture is the only way to know what you're looking at.

Nothing overlaps the artwork. The label goes in the margin the art wasn't using
anyway — a **column at the side** when the work is narrower than the screen (the
common case: median aspect here is ~1.45 against a 1.78 display), or a **band
underneath** when it's wider. The backdrop is the artwork itself, blown up,
blurred and dimmed.

Images are composed at **exactly your screen resolution**, detected via
`system_profiler`. That means macOS neither scales nor crops them, so you stop
losing the top and bottom of every painting to "Fill Screen".

```bash
./artwall.py --raw                  # bare artwork, no label
./artwall.py --screen 3840x2160     # compose for a different display
./artwall.py --recompose            # re-download and rebuild everything
```

Composing overwrites the file, so `--recompose` re-downloads from source rather
than re-processing an already-composed image — otherwise the art would shrink
and the label double up on every pass.

Composing is the one feature with a dependency (Pillow). It degrades
gracefully: without Pillow the artwork still downloads, just unlabelled.

Each run also writes two files into `~/Pictures/artwall/`:

- **`GALLERY.md`** — artist and life dates, year, medium, origin, museum, the
  museum's own written description where one exists, and a link to the work's
  page. Grouped **Now showing** / **Up next** / **Previously shown**.
- **`.artwall.json`** — the metadata store `GALLERY.md` is generated from, with
  each work's `state` (`backlog` / `live` / `archive`). Delete it and you lose
  descriptions, not images.

Store entries deliberately outlive their images: they are both the dedup memory
(so a work is never fetched twice) and the reading history. With one image live,
the folder is no record of what you've seen.

### Written for a beginner

Museum prose is patchy — Cleveland usually has a wall label, the Art Institute
often doesn't for prints, and the Met's API carries none at all. Left at that,
about half of all works would show facts and nothing else. So the label carries
up to three sections:

| Section | Source | Coverage |
|---|---|---|
| **About this work** | the museum's own description | ~50% |
| **About the artist** | Wikipedia summary, first two sentences | most named artists |
| **Terms** | built-in `GLOSSARY`, matched on style and medium | most works |

The glossary exists because catalogue vocabulary is opaque to a newcomer —
*mezzotint*, *ōban*, *gouache*, *ukiyo-e* mean nothing until someone explains
them. Terms are matched as substrings against each work's style, medium, origin
and title, longest match first, capped at two so the label doesn't turn into a
dictionary.

Artist lookup retries with `(painter)` and `(artist)` suffixes, and rejects
disambiguation pages — plain "John Martin" returns *"John Martin may refer
to:"*, which is worse than no bio at all.

Both are cached in the store, so a rebuild never re-fetches them.

macOS gives no way to ask which wallpaper is currently displayed — the old
AppleScript hook returns `missing value` under folder rotation, and the Sonoma
private store holds no image paths. With one image live that no longer matters:
whatever is in `~/Pictures/Wallpapers/` *is* what you're looking at, and
`GALLERY.md` opens with it under **Now showing**.

## Install

Runs are manual by default:

```bash
./artwall.py
```

`./install.sh` installs two launchd agents, logging to
`~/Library/Logs/artwall.log`:

| Agent | When | Does |
|---|---|---|
| `com.jaedon.artwall.fill` | Sundays 08:00 | `--add 7` — fetches a week into the backlog |
| `com.jaedon.artwall.rotate` | daily 07:00 | `--rotate` — archives the live image, promotes one from the backlog |

Remove them with:

```bash
launchctl bootout gui/$(id -u)/com.jaedon.artwall.fill
launchctl bootout gui/$(id -u)/com.jaedon.artwall.rotate
rm ~/Library/LaunchAgents/com.jaedon.artwall.*.plist
```

If the backlog is empty when `--rotate` runs, it fetches one directly and says
so on stderr — the desktop never goes stale, but a warning in the log means the
weekly fill didn't run.

### The live image has a fixed name

`~/Pictures/Wallpapers/current.jpg` — always that path, whatever the work.

macOS does not track the folder. Its stored config is `type: imageFile`, pinned
to one **filename**, so giving each day's image its own descriptive name broke
the reference every morning:

- the **lock screen** re-reads from disk, found nothing, and fell back to the
  system default;
- the **desktop** kept rendering a cached copy of the file that had gone, which
  looked like the wallpaper being stuck on one painting for days.

Both symptoms, one cause. The catalogue name is restored when the image is
archived, so `archive/` still reads as a gallery.

Re-pointing macOS at `current.jpg` is a one-time manual step; after that the
path never changes again.

### Making macOS notice

Swapping the file is not enough. `WallpaperAgent` caches its chosen image, and
with a folder set to shuffle it was observed **not to re-evaluate for two days**
— the store's `LastUse` stayed frozen while the folder changed underneath it, so
the same painting stayed on screen. Two things are needed on every swap:

- **`os.utime(dest, None)`** — `shutil.move` preserves mtime, so a promoted
  image can carry a timestamp days old. To a folder scan, nothing looks new.
- **`killall WallpaperAgent`** — forces a re-read. launchd restarts it
  immediately; the only visible effect is a brief flicker.

`nudge_macos()` does the second, and it's the load-bearing half. Restarting the
agent moved the store's `LastUse` from two days stale to the current second.

Either way, one manual step is needed once — macOS moved wallpaper state into a
private store in Sonoma, so this can't be scripted reliably:

> System Settings → Wallpaper → scroll to the bottom → **Add Folder** →
> `~/Pictures/Wallpapers` → set *Change picture: Every day* + **Random order**

Since images are already composed at screen resolution, either "Fill Screen" or
"Fit to Screen" works — there's nothing left to scale.

### Matching the lock screen

macOS keeps two wallpaper contexts — `AllSpacesAndDisplays` (desktop) and
`SystemDefault` (lock screen). Pointing both at the same folder is not enough:
they shuffle **independently**, each holding its own current pick, so with N
images they agree roughly 1 day in N. There is no setting to link the choice.

The fix is to remove the choice. The live folder holds exactly **one** image
and `--rotate` swaps it. Two shufflers over a one-item folder can only land on
the same image. You still get a new work daily — the rotation comes from artwall
moving files rather than from macOS picking among many.

## Usage

```bash
./artwall.py                                       # fill the backlog (weekly job)
./artwall.py --rotate                              # swap today's image (daily job)
./artwall.py --list                                # status across all three folders
./artwall.py --topics "bauhaus,constructivism" --add 12
./artwall.py --sources met --add 5                 # one source only
```

| Flag | Default | Notes |
|---|---|---|
| `--add` | 7 | how many to fetch into the backlog |
| `--rotate` | — | archive the live image, promote one from the backlog |
| `--home` | `~/Pictures/artwall` | holds `backlog/`, `archive/`, catalogue |
| `--live` | `~/Pictures/Wallpapers` | the folder macOS points at |
| `--min-width` | 3000 | raise to 3800 for a 5K Studio Display |
| `--min-ratio` | 1.2 | width/height; keeps things landscape-ish |
| `--topics` | see `TOPICS` | comma-separated full-text search terms |
| `--sources` | all | subset of `aic,cma,met` |
| `--raw` | off | save the bare artwork with no label |
| `--screen` | detected | compose for this size, e.g. `2560x1440` |
| `--recompose` | — | re-download and rebuild everything, then exit |

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
