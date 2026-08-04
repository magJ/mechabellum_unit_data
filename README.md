# Mechabellum Unit Stats Extractor

Extracts unit stats directly from the installed Mechabellum game files into a CSV.

## Usage

```
uv run python extract_unit_stats.py
```

Writes `mechabellum_units.csv` with one row per unit: id, name, special_unit,
test_unit, category, cost, hp, atk, speed, range, attack interval, splash
range, target type, flying, combat_size, move type, units per card, group,
unlock_price, slot_size, and card_width/card_height.

Options:

```
uv run python extract_unit_stats.py --game-root "/path/to/Mechabellum" --out units.csv
uv run python extract_unit_stats.py --standard-only   # drop non-roster cards entirely
```

By default it looks for the game at the standard macOS Steam install path.

## Standard vs. non-standard units

Not every card in the game's data is a normal, player-deployable unit. The
`special_unit` / `test_unit` columns are the game's own
`CardData.specialUnit` / `isTestUnit` flags, read straight through (not
guessed from names or IDs) so no resolution is lost; `category` is just a
human-readable label derived from `special_unit`. The standard roster is
`special_unit == 0` and `test_unit == False` (or pass `--standard-only`).

`special_unit` values:

- **0 — Standard** — the normal roster.
- **1 — Rotating bonus-pick** — cards that fill a separate, rotating
  bonus-unit slot rather than a permanent roster spot — which is also why
  Death Knell appears twice: once as the base card, once as its
  Experimental upgrade. Their card subtitles do say "Titan" ("High Damage
  Titan"), but don't confuse that with the *size*-tier Titan below — this
  is a different mechanic that happens to reuse the word.
- **2 — Experimental** — confirmed in-game term: the game has a real
  "Experimental Unit" name/buff string applied to Tech Tree upgrade units,
  all of which carry this flag. A couple of unused/internal cards (e.g.
  Supply Ship) share the flag without being Experimental-branded in their
  own text, so treat those as anomalies rather than true Experimentals.
- **3 — Combat-spawned** — no in-game term found for this one; it's our own
  descriptive label for units that only appear as another unit's spawned
  offspring (Larva, Spider Mine), never directly deployable.

`specialUnit` isn't a named C# enum in the compiled code (no symbol table
for it), so "Experimental" was confirmed by reading the game's own
localization strings (buff names) rather than by guessing from unit names
or IDs.

## Unit size / unlock tier

The combat `mechType` field (exposed as `combat_size`: Small/Medium/Huge)
doesn't match how players actually perceive unit size — it's a targeting
class, not a roster tier, and doesn't track cost cleanly (e.g. tier-1 units
span both Small and Medium `combat_size`).

What *does* track player-visible size is the standard roster's unlock
structure, all read straight from `CardData`:

- **`group`** (1-4) — the roster tier, which also sets `unlock_price`:
  - 1 → free — both the cheapest units (cost 100) and a cost-200 tier that's
    usually a similar footprint
  - 2 → 50-100 supply — "intermediate" units (Farseer, Scorpion, Typhoon,
    Hacker, ...)
  - 3 → 200 supply — "Giant" units (Melting Point, Fortress, ...)
  - 4 → 350 supply — **Titan** units: War Factory, Mountain, Abyss
- **`slot_size`** — an undocumented int that scales cleanly with the above
  (6-8 for the cheapest units, up to 70 for Titans) — the closest thing to
  an actual tile/footprint count in the data.
- **`card_width` / `card_height`** — decoded from `CardData.cardBaseSize`.
  These are the card *portrait's* render dimensions in the menu UI, not a
  battlefield footprint, but included for completeness.

`group` is `0` for every non-standard card (Experimental/spawned/rotating
cards aren't slotted into this progression), so use `slot_size` instead if
you need a size comparison across the full non-standard set too.

## Hits-to-kill matrix & interactive page

```
uv run python build_kill_matrix.py
```

Reads `mechabellum_units.csv` (standard roster only) and writes:

- `hits_matrix_base.csv` — a wide attacker × defender matrix, `ceil(defender
  HP ÷ attacker ATK)`, blank where the attacker can't target the defender
  (ground-only vs. a flyer, etc.)
- `hits_matrix_upgrades.csv` — long format, every matchup across all 9
  ATK-upgrade × HP-upgrade tech-tree combinations, with a `hits_delta` vs.
  baseline column for pivoting
- `units_data.json` — everything `index.html` fetches to build the page:
  `{languages: [...], units: [...], upgradeTerms: {...}}`. Each unit's
  `names` array and each `upgradeTerms` entry (`atk1`/`atk2`/`hp1`/`hp2`) is
  indexed the same way as `languages`.

`index.html` is a standalone page (open it directly, or host it on GitHub
Pages) with toggle buttons for both tech-tree upgrade tiers plus the Senior
Attack/Defense Specialist cards, color-coded by hits saved/lost vs. the
no-upgrade baseline. ATK/HP Upgrade 2 auto-enables (and disabling Upgrade 1
auto-disables) Upgrade 1, matching the game's own prerequisite; the
Specialist cards are independent of the tech tree and of each other, per
their in-game behavior as separately-purchased commander cards.

The four tech-upgrade buttons use the game's own button text verbatim
(`GameRiver.BlueprintData` term keys, confirmed by their descriptions
matching our +12/+24/+15/+30% model): **"Attack Enhancement"**, **"Attack
Enhancement II"**, **"Defense Enhancement"**, **"Defense Enhancement II"**.
Two things worth knowing if you're comparing against the game's UI: it's
"Defense" (American spelling), and neither tier-1 label carries a "I" --
only tier 2 gets "II" -- for *both* ATK and HP, not just HP. That's the
game's own text as extracted, not a guess.

The small "A/文" control in the top-right switches the page's language. It
defaults to matching the browser's language (`navigator.languages`, falling
back to English for anything the game doesn't ship), then remembers
whatever you pick after that via `localStorage`. Unit names and the four
upgrade button labels come from the game's own I2 Localization data
(`extract_unit_stats.find_language_list` reads the real language list --
name, code, and fixed ordering -- straight from the same
`LanguageSourceAsset` the unit names come from, rather than a hardcoded
guess). Everything else on the page (headings, legend, summary labels, the
Senior Specialist card names, tooltip text) has no in-game source, so those
are our own translations into all 11 languages (`UI_STRINGS` in
`index.html`) -- good-faith, not verified by native speakers or the game's
own localization team.

The dropdown's own labels (what you see in the closed select before picking
a language) are each language's name for itself, not English -- "Русский",
not "Russian". `find_language_list`'s raw entries are the game's *English*
label for each ("Russian", "French", ...); `build_kill_matrix.resolve_native_language_names`
swaps those for the real autonym, sourced from the game's own
"Language/English", "Language/Russian", etc. terms (each one's translation
into its own language is exactly the language's name for itself -- verbatim
game text, same as the upgrade button names). Chinese keeps its two
already-distinct native names as-is (简体中文 / 繁体中文); Spanish's two
game locales share one generic "Language/Spanish" term with no
region-specific native text, so those two get a plain "(España)" /
"(Latinoamérica)" suffix added onto the extracted "Español" -- the one spot
where we compose rather than extract verbatim. (One curiosity if you go
poking at the raw data: the game's own Polish translation of "Polish" is
"Polskie", an adjectival form rather than "polski" -- kept as-is rather
than silently corrected, consistent with treating the game's text as
ground truth rather than something to edit.)

**Local testing note:** `index.html` loads `units_data.json` via `fetch()`,
which browsers block on a bare `file://` page. Serve the folder instead,
e.g. `python3 -m http.server` here and open `http://localhost:8000/` — this
isn't an issue once it's hosted on GitHub Pages.

**Keeping it up to date:** after a game patch, re-run
`extract_unit_stats.py` then `build_kill_matrix.py` to regenerate
`units_data.json`, then commit and push — `index.html` itself needs no
changes.

### Deploying to GitHub Pages

`.github/workflows/deploy-pages.yml` publishes the repo root on every push
to `master` (or manually via the Actions tab's "Run workflow" button). One
manual step is required once per repo: in **Settings → Pages**, set
**Source** to **GitHub Actions** (not "Deploy from a branch" — that's a
different mechanism and won't pick up this workflow). After that, every
push to `master` redeploys automatically.

## How it works

Mechabellum is a Unity/IL2CPP game. Unit balance data lives inside two
MonoBehaviour assets baked into the boot scene: `ConfigDataContainer` (cost,
HP, ATK, speed) and `MechSkillGroupData` (range, attack interval, splash,
air/ground targeting). Unit names come from the game's localization data.

Because the game is IL2CPP-compiled, the schema needed to parse that data
isn't stored in the data files themselves — the script reconstructs it at
runtime straight from the game's own compiled binary
(`GameAssembly.dylib` + `global-metadata.dat`). This means it keeps working
across balance patches and new units with no manual re-mapping.

`GameAssembly.dylib` ships as a universal (multi-architecture) binary, but
the schema-generation step needs a single-architecture one. `extract_unit_stats.py`
thins it into `tools/extracted/GameAssembly.thin.dylib` on first run (via
`lipo`) and reuses that cached copy afterwards, re-thinning automatically if
the game updates. `tools/` is gitignored — it's a derived copy of the
installed game's binary, not something to commit or redistribute — so
there's nothing to fetch manually; just run the script and it regenerates
itself against whatever copy of the game is on your machine.

## Re-running after a game update

Just run it again — it re-derives the schema from whatever's currently
installed. If a future update actually restructures these C# classes, the
script's built-in sanity checks will raise an error rather than silently
producing wrong numbers.

## Requirements

- `uv` (dependencies are managed via `pyproject.toml` / `uv.lock`)
- macOS with the game installed via Steam
