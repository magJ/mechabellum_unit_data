# Mechabellum Hits-to-Kill Matrix

Extracts unit stats straight from the installed Mechabellum game files and
builds an interactive matrix showing how many hits (or how long) it takes
for any unit to kill any other, factoring in attack/HP upgrades.

## Usage

```
uv run python extract_unit_stats.py
```

Writes `units_data.json`. Open `index.html` in a browser to see the matrix
(or host it — see Deploying below).

```
uv run python extract_unit_stats.py --game-root "/path/to/Mechabellum" --out units.json
```

By default it looks for the game at the standard macOS Steam install path.

**Local testing:** `index.html` loads `units_data.json` via `fetch()`,
which browsers block on a bare `file://` page. Serve the folder instead —
e.g. `python3 -m http.server` here, then open `http://localhost:8000/`.
Not an issue once hosted on GitHub Pages.

## Where things live

- `extract_unit_stats.py` — the only extraction script. Pulls everything
  from the installed game into `units_data.json`: unit/card stats in every
  language the game ships, the four tech-upgrade names, and the damage-ramp
  tables a couple of units need. All the hits-to-kill / time-to-kill math
  and upgrade scenarios are computed live in the browser from that one
  file — nothing else is precomputed or serialized.
- `index.html` — the standalone interactive page.
- `NOTES.md` — non-obvious things about the game's data worth knowing
  before changing either file above (what counts as a "standard" unit, the
  damage-ramp mechanic, translation sourcing, and so on).

## Re-running after a game update

Just run `extract_unit_stats.py` again — it re-derives everything from
whatever's currently installed, no manual re-mapping needed. If a future
update actually restructures the underlying C# classes, it'll raise an
error rather than silently produce wrong numbers.

## Deploying to GitHub Pages

`.github/workflows/deploy-pages.yml` publishes the repo root on every push
to `master` (or manually via the Actions tab). One manual step is needed
once per repo: in **Settings → Pages**, set **Source** to **GitHub
Actions** (not "Deploy from a branch").

## Requirements

- `uv` (dependencies are managed via `pyproject.toml` / `uv.lock`)
- macOS with the game installed via Steam
