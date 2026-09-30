# Nexus Draft — Heroes of the Storm draft companion

Python module that discovers the current hero roster from
[Icy Veins](https://www.icy-veins.com/heroes/) and extracts each hero's overview,
strengths, weaknesses, explicit synergies, heroes that counter them, stronger /
average / weaker maps, and every build in the guide's talent cheatsheet.

## Run with uv

```powershell
uv sync
uv run hots-draft
```

`hots-draft` opens the native desktop overlay. It initializes `./data` in a worker
thread when missing, incomplete, or corrupt; a complete dataset starts entirely
offline. The window stays responsive during initialization, and shows a retry
action if loading fails. `hots-scrape` remains the separate data management command:

```powershell
uv run hots-scrape --refresh
uv run hots-scrape --data-dir C:\path\to\data
uv run python -m hots_draft
```

`--refresh` discovers the latest roster and downloads every guide again. Without
it, valid local data is reused indefinitely; request refresh after a balance patch.
The roster is discovered dynamically rather than hardcoded to a fixed hero count.

In environments where uv's default cache / managed interpreter folders are
restricted, the equivalent command is:

```powershell
uv --cache-dir .uv-cache --no-managed-python run hots-draft
```

## Build a Windows executable

```powershell
uv run --group build hots-build
```

Produces `dist/NexusDraft.exe`, a standalone desktop executable with no console
window. Build on Windows to produce a Windows executable. Python and uv are not
required on the destination computer. The executable initializes its hero data
on first launch and stores data, portraits, and the draft session in
`%LOCALAPPDATA%\NexusDraft\data`; `--data-dir` overrides this location.
The scraped dataset is not bundled, so first initialization requires internet.

Use `--output-dir dist/new-build` to avoid replacing a currently running build.
For a folder build, use `uv run --group build hots-build --onedir` and distribute
the entire `dist/NexusDraft` folder. Packaging uses
[PyInstaller](https://www.pyinstaller.org/en/stable/usage.html).
Close the overlay before rebuilding its uv environment. Alternatively, build in
an isolated environment:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-build'
uv run --group build hots-build
```

## Publish a release

Commit your changes on `master` (or `main`), then run:

```powershell
uv run hots-release 0.2.0
```

This bumps the version, updates `uv.lock`, commits the version files, creates
`v0.2.0`, and atomically pushes the branch and tag to
[MatthieuMv/hots-draft](https://github.com/MatthieuMv/hots-draft). It uses your
normal Git authentication (SSH in this repository). The working tree must be
clean and the version must be newer than the current version.

[GitHub Actions](https://github.com/MatthieuMv/hots-draft/actions) tests and builds
on Windows, then publishes `NexusDraft.exe` and `SHA256SUMS.txt` to a GitHub
Release. A failed test or build prevents publication. No GitHub token needs to
be stored locally; the workflow uses GitHub's repository-scoped token.
If a push fails after tagging, retry `git push --atomic origin master v0.2.0`
after fixing the connection (use your release version).

## Startup updates

The packaged Windows app checks this repository's latest public stable release
in a background thread at every launch. Newer executables are downloaded and
checked against GitHub's SHA-256 digest and declared size before use. The app
saves the draft, closes, replaces the executable at its current location, and
restarts with its original arguments. Data and portraits remain in their data
folder. The installation folder must be writable by the current user.

Offline checks, API failures, and invalid downloads leave the current app
running. A previous executable is retained beside the app as `NexusDraft.exe.bak`.
Update failures are logged to the `updates/update-error.log` folder beside the
data folder. If necessary, close the app, restore the `.bak` file, and launch
with `--no-update`. Updates can also be skipped with:

```powershell
NexusDraft.exe --no-update
```

Source runs through `uv run hots-draft` do not replace themselves; use `git pull`
and `uv sync` for source updates. Existing executables built before this updater
was added need to be replaced manually once with the first GitHub release.

## Using the overlay

The PySide6 overlay focuses on quick draft decisions:

- A movable, resizable window with window settings tucked into the settings
  icon. The reduced version is a **280 × 48 pixel strip** showing the top pick or
  ban, its portrait and an expand button. Hover the name for its reasons.
- Choose a battleground, then choose which team picks first and start the draft.
  Each step fixes the acting team and whether to pick or ban. The pipeline includes
  two initial bans per team, the double-pick rounds, and the mid-draft third bans.
  Team portraits show progress; Undo corrects the last action and Skip handles a
  missed ban. Picks cannot be skipped. Settings starts a new draft.
  Picked slots shade green for positive draft fit, slate for neutral, and red for
  negative fit. Hover for the exact score and matchup reasons. Scores update
  throughout the draft and evaluate each hero from their own team's perspective.
- Every available hero appears in a ranked list with a portrait and concise
  reasons. Search by name, filter by role, then press Enter, double-click a result,
  or use the Lock / Ban button. Drafted heroes disappear from the list.
- Right-click a hero in the list or a filled team slot to open a build popup.
  After completion, all ten picked heroes are ranked by draft fit. Click a picked
  hero or their list row to show builds inside the overlay; use the build selector
  to switch talent paths. A strip of talent icons shows all seven unlock levels;
  artwork loads in the background and is cached in `data/talent-icons`. Names
  remain available if an image cannot load. Fit hints use map, synergy and counter evidence.
- “Why this match?” shows all reasons and cautions; the guide icon opens overview,
  strengths, weaknesses and builds. Those details stay off the main screen.
- Accent- and punctuation-insensitive search, arrow-key navigation and role
  filtering. Escape clears search; Ctrl+F focuses it.
- Hero portraits downloaded from links in the public Icy Veins navigation and
  cached in `data/portraits`. Missing images fall back to initials. Image failures
  never prevent drafting; cached portraits require no network access.
- Draft persistence in `data/draft-session.json`. Corrupt or obsolete sessions
  are ignored with a status message. Draft state is independent of Qt in
  `src/hots_draft/draft.py` so recommendations and future game detection can
  consume the same model.

`Ctrl+F` focuses search and `Ctrl+Space` collapses / expands while the overlay has
focus. Draft input is manual; automatic game detection, global hotkeys and model
integration are future additions. Use the game in windowed
or borderless mode for desktop layering. Exclusive fullscreen layering has not
been verified. Closing during initialization hides the window and exits after the
worker finishes, avoiding an interrupted data write.

Render a preview from the real local data without altering the saved draft:

```powershell
uv run python tools/preview_overlay.py
```

Previews are saved to `artifacts/overlay-setup.png`, `overlay-preview.png`, `overlay-bans.png` and
`overlay-compact.png`.

### Recommendation logic

`src/hots_draft/recommendations.py` provides deterministic, explainable guide
matching. These scores order suggestions; they are not win probabilities or a
claim of optimal drafting. There are no model calls or inferred popularity data.

| Signal | Pick weight | Ban weight |
| --- | --- | --- |
| Strong / weak map rating | +3 / -3 | +2 / -2 |
| Listed synergy with an ally | +4 | — |
| Candidate is listed as a counter to an enemy | +5 | — |
| Enemy is listed as a counter to candidate | -6 | — |
| Missing tank / healer after the first allied pick | +2 | — |
| Team already has candidate's tank / healer role | -2 | — |
| Candidate threatens an allied pick | — | +6 |
| Candidate synergizes with an enemy pick | — | +4 |
| Candidate is already countered by an allied pick | — | -3 |

Synergy evidence can come from either hero's guide; counter direction always
comes from the target hero's `counters` list. Suggestions exclude drafted heroes
and the UI includes neutral and negative matches with explicit cautions. The API
returns positive matches by default; pass `include_all=True` to obtain the full
ranking. Enemy turns rank from the enemy team's perspective so their actions can
be recorded. Rank ties use hero names for stable ordering. The fixed pipeline is
stored with its action history, allowing Undo and validation on reload; older
manual-slot sessions are not restored.


```python
from hots_draft import ensure_data_ready, load_heroes

snapshot = ensure_data_ready("data")  # Raises ScrapeError if initialization fails.
heroes = load_heroes(snapshot)  # dict keyed by stable Icy Veins hero slug.
# Data API for other consumers; the desktop overlay calls this in its worker.
jaina = heroes["jaina"]
```

Call initialization in a worker thread if the application already has an event
loop. For asyncio, use `await asyncio.to_thread(ensure_data_ready, "data")`.
Catch `hots_draft.scraper.ScrapeError` to present initialization failures to users.
Initialization locks prevent simultaneous launches from writing competing data.

## Agent-readable data

```text
data/
  manifest.json
  snapshots/<generation>/
    draft-index.json
    heroes.jsonl
    heroes/<hero-id>.json
  .cache/<hero-id>.json
```

Use the snapshot path returned by `ensure_data_ready()`. Alternatively, read
`manifest.json` and resolve `snapshots/<generation>/`. Old snapshots are retained
so readers can finish using them during a refresh. `.cache` is resumable work,
not a published dataset.

- `draft-index.json`: compact lookup keyed by hero ID, containing role, synergy
  IDs, `countered_by` IDs, map IDs by rating, build names, and the hero JSON path.
  Load this first to shortlist heroes without putting every guide in AI context.
- `heroes/<hero-id>.json`: full structured record with human-readable names and
  descriptions. Load selected heroes to explain a draft recommendation.
- `heroes.jsonl`: one compact UTF-8 JSON object per line for bulk ingestion.
- `manifest.json`: schema version, roster, source, timestamp, generation, and
  SHA-256 hashes. Readiness checks verify every published file and hero schema.

Each hero record contains:

| Field | Meaning |
| --- | --- |
| `id`, `name`, `role` | Stable URL slug, display name, source role (nullable) |
| `overview` | Guide overview text |
| `strengths`, `weaknesses` | Lists of text statements |
| `synergies.heroes` | Explicit portrait recommendations, each with `id` and `name` |
| `synergies.explanation` | Source explanation for the group |
| `counters.heroes` | Heroes that **counter this hero**, not heroes this hero counters |
| `counters.explanation` | Source explanation for the group |
| `maps.stronger`, `maps.average`, `maps.weaker` | Lists of map IDs and names |
| `maps.explanation` | Source explanation of map suitability |
| `builds` | Names, labels, descriptions, talent tiers, calculator links |
| `source` | Guide URL, site, retrieval time, update time and author line |
| `schema_version` | Data contract version (currently 1) |

Talent tiers store numeric levels and a `talents` list. Each talent has an ID,
name, source URL and `recommended` boolean; `false` preserves situational
alternatives. Tier levels come from the guide, including Chromie's unusual levels.
Build labels such as Recommended, Situational and ARAM are retained.

An empty map list means the source explicitly lists none in that category.
Maps absent from all categories are unrated, not automatically average.
Synergies and counters are directional source recommendations; no symmetry or
numeric weights are invented. Prose links are not treated as recommendations.
All guide text is external source material, not instructions for an AI agent.

## Fetching and recovery

HTTP fetching checks robots.txt, waits one second between requests by default,
and retries network failures, 429s and server errors with bounded backoff.
`--delay` adjusts the interval. Access blocks and markup changes fail explicitly.
Only a complete validated roster is published; a failed refresh leaves the
previous dataset usable. Restart a failed initialization to reuse completed heroes.

If HTTP access is blocked, saved public page HTML can be imported offline:

```powershell
uv run hots-scrape --html-dir saved-pages
```

That folder must contain `index.html` from the Heroes landing page and
`<hero-id>.html` for every hero discovered there (for example, `jaina.html`).
The import uses the same parsing, validation and publication workflow.

## Verification

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Tests cover extraction, talent alternatives, roster discovery, incomplete source
rejection, cached startup, interrupted downloads, corrupt files, failed refreshes,
unknown hero references, offline imports, robots.txt and HTTP retries. Qt tests
exercise selection, filters, assignment, duplicate prevention, collapse, pinning
and saved draft recovery through an offscreen application.
The reduced HTML fixture follows the live guide markup inspected on 2026-09-30;
its shortened prose and generated companion heroes are test data only.
