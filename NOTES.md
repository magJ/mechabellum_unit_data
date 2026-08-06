# Notes on the data and how it's extracted

This is for whoever (human or LLM) next touches this codebase. It covers
things that aren't obvious from the game itself or from a quick read of
`extract_unit_stats.py` — game-data quirks discovered while building this,
and how the extraction actually works under the hood.

## How the extraction works

Mechabellum is a Unity/IL2CPP game. Unit and card balance data lives inside
two MonoBehaviour assets baked into the boot scene (`level0`):
`GameRiver.ConfigDataContainer` (cardDatas + mechDatas: cost, HP, ATK,
speed, ...) and `GameRiver.MechSkillGroupData` (range, attack interval,
splash, targeting).

Because the game ships IL2CPP-compiled code, Unity's "TypeTree" (the schema
saying which bytes mean which field) isn't stored in the data files
themselves. The script reconstructs it at runtime from the game's own
compiled binary (`GameAssembly.dylib` + `global-metadata.dat`) via
`TypeTreeGeneratorAPI`, rather than hand-mapping byte offsets — this is
what lets it keep working across balance patches and new units with no
manual changes, as long as the C# classes' *shape* doesn't change (if it
does, the script's sanity checks raise loudly instead of producing
plausible-looking wrong numbers).

`GameAssembly.dylib` ships as a universal binary; the schema step needs a
single architecture, so the script thins it into
`tools/extracted/GameAssembly.thin.dylib` on first run (via `lipo`) and
reuses/re-thins that cache automatically. `tools/` is gitignored — it's a
derived copy of the installed game's binary, regenerated on demand, not
something to commit.

Unit/card names and the four upgrade-button labels come from the game's I2
Localization data, read via a small hand-rolled binary parser rather than
the generic TypeTree path — the term table has thousands of entries and
only a handful of specific keys are ever needed, so it isn't worth fully
modeling in TypeTree terms. See `get_localized_names` / `find_language_list`
for the exact binary layout.

## Standard vs. non-standard units

`specialUnit` (raw `CardData` field, 0-3) + `testUnit` distinguish the
normal roster from other card types. `index.html` only shows
`specialUnit == 0 && !testUnit` (32 units as of writing) — mixing in the
rest would make the hits-to-kill matrix apples-to-oranges.

- **0 — Standard** — the normal roster.
- **1 — Rotating bonus-pick** — a separate mechanic, not a permanent roster
  spot. Death Knell's two variants are the only examples, which is why
  Death Knell appears twice in the raw data (base card + Experimental
  upgrade). Their card subtitle text does say "Titan" ("High Damage
  Titan") — don't confuse this with the *size-tier* Titan below, which is
  a different concept that happens to reuse the word.
- **2 — Experimental** — confirmed in-game term (a real "Experimental
  Unit" buff/name string exists). Tech Tree upgrade cards, plus a couple
  of internal-only cards (e.g. Supply Ship) that share the flag without
  being true Experimentals.
- **3 — Combat-spawned** — our own label; no in-game term found. Units
  that only appear as another unit's spawned offspring (Larva, Spider
  Mine), never directly deployable.

## The two meanings of "Titan"

- `group == 4` (`unlockPrice` 350) is the real size/cost tier players call
  "Titans": War Factory, Mountain, Abyss. All `specialUnit == 0`, standard
  roster.
- `specialUnit == 1` (Death Knell) is the unrelated "rotating bonus-pick"
  mechanic above, whose card text *also* happens to say "Titan".

`combatSize` (Small/Medium/Huge, from `MechData.mechType`) is a third,
unrelated axis — a targeting/splash class, not a size tier, and doesn't
track cost cleanly (tier-1 units span both Small and Medium `combatSize`).
`group`/`unlockPrice`/`slotSize` are what actually track player-perceived
size. `group` is `0` for every non-standard card.

## Unit ordering

`sort` (`CardData.sort`) is the game's real unlock/modification-screen
order, unique across the standard roster — not `id`, which jumps around
(newer units like Mountain got id 2002). Non-standard cards all share
`sort == 0`; the extractor falls back to cost then id for those.

## Damage ramp (Melting Point, Steel Ball)

These two don't deal flat per-hit damage. Their weapon (`LaserSkillData`)
has a `damageMultiplier` field: a 29-entry table where the Nth consecutive
hit against the same target deals `atk * table[min(N-1, 28)]` — first hit
is ~1-4% of ATK, ramping to ~47x ATK by hit 29, then capped there. This is
the game's actual lookup table (confirmed by checking its description
text: "Increases the ATK/HP of all units by {0}%" on the tech that scales
it), not a fitted curve — polynomial/power-law fits to the raw numbers were
tried and rejected before the literal array was found.

Anything computing hits-to-kill must simulate tick-by-tick for a unit with
a non-null `rampMultipliers`, not use `ceil(hp/atk)`. Practical effect:
ramping units look *worse* than raw ATK suggests against low-HP targets
(they die before the ramp matters — 6 hits to kill a 263-HP Crawler) and
much better against tanky ones (26 hits for a 43,938-HP Fortress; naive
flat-damage math would say 2 and 262 respectively).

## Upgrade button text

The four tech-tree upgrade names are extracted verbatim from
`GameRiver.BlueprintData` (ids 4/401/5/501, confirmed by their description
text matching the +12/+24/+15/+30% model): **"Attack Enhancement"**,
**"Attack Enhancement II"**, **"Defense Enhancement"**, **"Defense
Enhancement II"**. Two quirks if cross-checking against the game's UI:
it's American "Defense" not "Defence", and *neither* tier-1 label carries
a numeral — only tier 2 gets "II" — for both ATK and HP. Not a bug here.

The "Senior Attack/Defense Specialist" cards have no confirmed in-game
term (checked `OfficerData`'s ~30 "___ Specialist" commander cards, no
exact match on name + effect). These are user-supplied labels, translated
by us into all 11 languages — not extracted.

## Language picker labels

`LanguageSourceData.mLanguages` gives each language's name in *English*
("Russian", "French", ...) — fine internally, wrong for a picker. The real
autonym ("Русский") comes from the game's own `Language/Russian` (etc.)
term, taking that term's translation at the language's own index. Chinese
Simplified/Traditional already have distinct native names in `mLanguages`
itself. Spanish's two locales (`es-ES`/`es-US`) share one generic
`Language/Spanish` term with no region-distinguishing native text, so
those two get a manually composed "(España)"/"(Latinoamérica)" suffix —
the one label in the whole picker that isn't extracted verbatim.

Unrelated curiosities noticed along the way (not used, just for
transparency): the game's own Polish translation of "Polish" is "Polskie"
(adjectival, not the more standard "polski"), and its Korean translation
of "Polish" is "광택" (shoe-polish — a mistranslation). Left as found.

## Non-game-sourced UI translations

Everything in the page's UI text (`UI_STRINGS` in `index.html`) beyond
unit names and the four upgrade button labels has no in-game source —
headings, legend, tooltip copy, the Specialist card names. These are our
own good-faith translations into all 11 languages, not verified by native
speakers or the game's localization team.

## Simplifications in the hits/time model

- No armor, shields, splash falloff across multiple targets, accuracy, or
  building-damage multipliers.
- Time-to-kill (`hits × attackInterval`) assumes the attacker is already
  in range and firing back-to-back with no wind-up before the first shot.
- Upgrade bonuses are additive against the base stat, not compounded: both
  ATK tech upgrades together is `base × (1 + 0.12 + 0.24)`, not
  `base × 1.12 × 1.24`.
- Since attack speed isn't affected by any upgrade modeled here, time is
  always hits scaled by a constant — so the hits-based color coding
  (relative change from baseline) is identical whether the matrix is
  showing hits or time; only the displayed number changes.
