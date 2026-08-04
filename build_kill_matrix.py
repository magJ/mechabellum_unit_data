"""
Build a hits-to-kill matrix for every unit-vs-unit matchup, including the
effect of attack/HP upgrades, from the CSV produced by extract_unit_stats.py.

Model
-----
hits_to_kill(attacker, defender) = ceil(defender.hp / attacker.atk)

This is a simplified 1v1 raw ATK-vs-HP comparison. It does NOT account for
armor, shields, splash falloff across multiple targets, accuracy, or
building-damage multipliers -- none of which are in the extracted data.
It DOES respect air/ground targeting: a matchup is marked unreachable
("") if the attacker's weapon can't target the defender's air/ground class.

Upgrades are additive on top of the base stat, per the spec given:
  ATK upgrade 1: +12%    HP upgrade 1: +15%
  ATK upgrade 2: +24%    HP upgrade 2: +30%
  (upgrade 2's bonus adds to upgrade 1's rather than compounding, so a unit
  with both is base * (1 + 0.12 + 0.24), not base * 1.12 * 1.24)

Only the standard, directly-deployable roster is included by default --
Experimental/spawned/rotating cards have their own separate balance and
mixing them in would make the matrix apples-to-oranges. Use
--include-non-standard to include everything anyway.

Also writes units_data.json -- the minimal per-unit fields (id, name, hp,
atk, target, flying) that index.html fetches to build the interactive
matrix in the browser. Regenerate this after every extract_unit_stats.py
run so the page picks up balance changes / new units automatically.

Usage
-----
    uv run python build_kill_matrix.py [--units-csv mechabellum_units.csv]
        [--out-prefix hits] [--units-json units_data.json] [--include-non-standard]
"""

import argparse
import csv
import json
import math

ATK_UPGRADE_BONUS = {0: 0.0, 1: 0.12, 2: 0.12 + 0.24}
HP_UPGRADE_BONUS = {0: 0.0, 1: 0.15, 2: 0.15 + 0.30}


def load_units(path, standard_only):
    units = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if standard_only and not (row["special_unit"] == "0" and row["test_unit"] == "False"):
                continue
            units.append({
                "id": row["id"],
                "name": row["name"],
                "hp": float(row["hp"]),
                "atk": float(row["atk"]),
                "target": row["target"],
                "flying": row["flying"] == "True",
            })
    return units


def can_target(attacker, defender):
    t = attacker["target"]
    if not t or t == "None":
        return False
    if t == "Air & Ground":
        return True
    if t == "Ground Only":
        return not defender["flying"]
    if t == "Air Only":
        return defender["flying"]
    return False


def hits_to_kill(atk, hp):
    if atk <= 0:
        return None
    return math.ceil(hp / atk)


def write_base_matrix(units, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["attacker \\ defender"] + [u["name"] for u in units])
        for a in units:
            row = [a["name"]]
            for d in units:
                if not can_target(a, d):
                    row.append("")
                else:
                    row.append(hits_to_kill(a["atk"], d["hp"]))
            w.writerow(row)


def write_upgrade_long_format(units, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "attacker_id", "attacker_name", "defender_id", "defender_name",
            "atk_upgrade", "hp_upgrade",
            "attacker_atk", "defender_hp", "hits_to_kill",
            "hits_base", "hits_delta",
        ])
        for a in units:
            for d in units:
                if not can_target(a, d):
                    continue
                hits_base = hits_to_kill(a["atk"], d["hp"])
                for atk_lvl, atk_bonus in ATK_UPGRADE_BONUS.items():
                    eff_atk = a["atk"] * (1 + atk_bonus)
                    for hp_lvl, hp_bonus in HP_UPGRADE_BONUS.items():
                        eff_hp = d["hp"] * (1 + hp_bonus)
                        hits = hits_to_kill(eff_atk, eff_hp)
                        w.writerow([
                            a["id"], a["name"], d["id"], d["name"],
                            atk_lvl, hp_lvl,
                            round(eff_atk, 1), round(eff_hp, 1), hits,
                            hits_base, hits - hits_base,
                        ])


def write_units_json(units, path):
    payload = [
        {
            "id": int(u["id"]),
            "name": u["name"],
            "hp": u["hp"],
            "atk": u["atk"],
            "target": u["target"],
            "flying": u["flying"],
        }
        for u in units
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units-csv", default="mechabellum_units.csv")
    parser.add_argument("--out-prefix", default="hits")
    parser.add_argument("--units-json", default="units_data.json")
    parser.add_argument("--include-non-standard", action="store_true")
    args = parser.parse_args()

    units = load_units(args.units_csv, standard_only=not args.include_non_standard)
    units.sort(key=lambda u: int(u["id"]))

    base_path = f"{args.out_prefix}_matrix_base.csv"
    upgrades_path = f"{args.out_prefix}_matrix_upgrades.csv"

    write_base_matrix(units, base_path)
    write_upgrade_long_format(units, upgrades_path)
    write_units_json(units, args.units_json)

    print(f"{len(units)} units included")
    print(f"Wrote base matrix ({len(units)}x{len(units)}) to {base_path}")
    print(f"Wrote upgrade scenarios (long format) to {upgrades_path}")
    print(f"Wrote {args.units_json} for index.html")


if __name__ == "__main__":
    main()
