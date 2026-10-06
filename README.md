# HeatSync Labs blog archive, 2009–2013

A browseable copy of the original `heatsynclabs.org` WordPress blog: **241 posts, 19 pages, 615 photographs**, spanning **2009-07-26 → 2013-10-23**.

**→ [Read it](https://heatsynclabs.github.io/blog-archive/)**

The blog ran from the first public meeting in a Mesa police lodge through the RepRap build, the SyncFleet near-space balloon, the laser-cutter Kickstarter and the move into 140 W Main, then went quiet. This is all of it, with its photographs, as published.

## Read it

**Browse the site** — timeline, calendar and search, in light or dark.

```sh
python3 -m http.server 8787     # then open http://localhost:8787/
```

Plain static HTML/CSS/JS, no build step and no dependencies. `index.html` loads `data/posts.json` and fetches a pre-rendered body from `data/html/`, so there is no Markdown parser in the browser.

**Or read the Markdown directly.** Every entry is also a plain file in [`posts/`](posts/), which GitHub renders with its images inline. For example: [`posts/2010-08-29-syncfleet-launch-great-success.md`](posts/2010-08-29-syncfleet-launch-great-success.md).

## What's in here

| Path | What |
|---|---|
| `posts/` | 260 Markdown files, `YYYY-MM-DD-slug.md`, images at `../images/…` |
| `images/` | 615 originals, byte-for-byte copies of what the blog served (134 MB) |
| `thumbs/` | 480px JPEGs used by the grid views (16 MB) |
| `data/posts.json` | the index: date, title, author, excerpt, image count, thumbnail |
| `data/html/` | pre-rendered post bodies, images at `images/…` |
| `assets/` | GANTRY v2.0 tokens, site CSS/JS, self-hosted fonts |
| `build/build.py` | regenerates everything from the WordPress database dump |
| `build/attribution.json` | curated authorship corrections, with the evidence for each |

## Rebuild

Everything outside `assets/`, `index.html` and `build/` is derived. Point the script at a directory holding `heatsynclabs-wp.sql` with the `www.heatsynclabs.org/` tree beside it:

```sh
python3 build/build.py --source /path/to/wordpress-export
python3 build/build.py --source … --skip-images     # text only, ~1 second
```

It parses the mysqldump into SQLite itself (the one-line `INSERT`s defeat `awk` and `grep`), resolves every image three ways — inline `<img>`, NextGEN galleries, and `_wp_attached_file` attachments — strips WordPress size suffixes to reach full-size originals, and writes both the Markdown and the HTML.

Thumbnails use macOS `sips`. On other platforms swap that one call in `make_thumb()`; everything else is pure Python 3 with no third-party packages.

Pushing to `main` redeploys the site automatically.

## Notes on fidelity

- **Images are originals.** Nothing was re-encoded; `thumbs/` is a separate derived copy for the grid views only.
- **No photograph the blog hosted is missing.** Verified two ways: no published entry references a NextGEN gallery that failed to resolve, and every entry that renders zero images was checked by hand — in all 10 cases the source only ever pointed off-site.
- **13 images were hotlinked, not hosted.** They came from `farm*.static.flickr.com`, PayPal and guestlistapp when the posts were written, so they were never the lab's files. **Every one is clickable**: 8 sit inside the link the original post already wrapped them in (which goes to the Flickr photo page), 3 that had no such wrapper were turned into links to the image itself, and 2 are PayPal tracking pixels, left unlinked because a 1×1 tracking GIF is not worth a click. Anchors are never nested.
- **7 Flash slideshows were Flickr photo sets.** This is the real photo loss, and it happened when the posts were written, not here: they embedded sets hosted on Flickr — accounts `25968780@N03` (the lab's `hslphotosync`), `zgiles` and `60761282@N03` — which never lived on the lab's server. Each is replaced by a block naming it and linking to the set, reconstructed from the `set_id` in the original flashvars. Most still resolve.
- **7 Flash players were video.** Vimeo `.swf` embeds, replaced by a link to the clip.
- **Post dates are WordPress `post_date`.** For *pages* that is the creation date, not the last edit — the About page is dated 2009 but its text was revised through 2012.
- **Ten 2009 posts had the wrong author, and are corrected.** `wp_posts.post_author` credits them to `huertanix`; they are not his. A WordPress *delete-user-and-reassign* operation moved every post belonging to user ID 4 onto that account, rewriting `post_author` on all of them. User 4 was **Drea (Andrea)**, `drea@heatsynclabs.org`, who held the WordPress *editor* role. Nine of the ten are dated before the `huertanix` account existed (it was registered 2009-11-13 04:30; his first genuine post is 74 minutes later), and four are signed `drea`/`Drea` in the body. The archive now credits Drea and carries the evidence on each post; the database column is deliberately left untouched, since its wrongness is what documents the deletion. See [`build/attribution.json`](build/attribution.json).

## Who wrote it

| Author | Posts | Span |
|---|---|---|
| `huertanix` (David Huerta, the elected Editor) | 130 | 2009-11 → 2011-07 |
| `rrix` (Ryan Rix) | 43 | 2011-07 → 2012-06 |
| `jjrosent` (Jacob Rosenthal) | 34 | 2011-11 → 2013-10 |
| `uberschnitzel` | 7 | 2009-07 → 2012-11 |
| `ricko` (Rick Oooooo) | 4 | 2009-07 → 2009-09 |
| `Sean Hillmeyer` | 4 | 2009-08 → 2009-09 |
| `will` (Will Bradley) | 4 | 2011-09 → 2012-06 |
| `blhack` (Ryan McDermott) | 3 | 2012-11 → 2013-01 |
| `Sierra` | 2 | 2009-09 |
| **Drea** (Andrea) — corrected, see below | **10** | 2009-08 → 2009-12 |

One person wrote 54% of it and stopped in July 2011, the same month the lab advertised for a replacement. Posts per year: **33 · 63 · 92 · 51 · 2**. The last entry launched a weekly format that never had a second issue.

## Theme

GANTRY v2.0, HeatSync Labs' own design system — square corners, block shadows, caution-tape amber, Archivo / Instrument Sans / IBM Plex Mono, with Charis SIL reserved for the wordmark.

The site opens in GANTRY's **light (paper + ink) theme** and carries a light/dark selector in the masthead. The choice is remembered in `localStorage` and applied by a small inline script in `<head>`, so a returning visitor gets their theme with no flash of the wrong one. With nothing stored it is always light — system preference is deliberately not consulted, so the default is predictable.

The masthead and footer stay dark in both themes on purpose: they use the system's always-dark *plate* ground, which is how GANTRY treats chrome.

## Provenance

Generated from `heatsynclabs-wp.sql`, a dump of the blog's own MySQL database taken from the lab's web server on **2026-09-01**. Row counts and image resolution were verified against it.
