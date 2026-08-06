"""
Extract Mechabellum unit stats from the installed game into units_data.json.

See NOTES.md for the game-mechanic details this relies on (why some units
appear twice, what "Titan" means in two different senses, the damage-ramp
table, etc.) and the comments in this file for the extraction mechanics
themselves (IL2CPP schema reconstruction, binary layout, ...).

Usage
-----
    uv run python extract_unit_stats.py [--game-root PATH] [--out units_data.json]
"""

import argparse
import json
import os
import struct
import subprocess
import sys

import UnityPy
from TypeTreeGeneratorAPI import TypeTreeGenerator
from UnityPy.helpers import TypeTreeHelper
from UnityPy.helpers.TypeTreeNode import TypeTreeNode

# UnityPy's compiled ("boost") typetree reader is stricter about node
# metadata than we can reliably reproduce from a freshly generated
# TypeTree (see fix_node_sizes below), so we use the pure-Python reader.
TypeTreeHelper.read_typetree_boost = None

DEFAULT_GAME_ROOT = os.path.expanduser(
    "~/Library/Application Support/Steam/steamapps/common/Mechabellum"
)

PRIMITIVE_SIZES = {
    "SInt8": 1, "UInt8": 1, "char": 1, "bool": 1,
    "SInt16": 2, "UInt16": 2, "short": 2, "unsigned short": 2,
    "SInt32": 4, "UInt32": 4, "int": 4, "unsigned int": 4, "float": 4,
    "SInt64": 8, "UInt64": 8, "long": 8, "unsigned long": 8, "double": 8, "long long": 8,
}

UNIT_TYPE_NAMES = {0: "Small", 1: "Medium", 2: "Huge"}
MOVE_TYPE_NAMES = {0: "Normal", 1: "Underground", 2: "Cloak"}

# See NOTES.md "Non-standard cards" for what these mean and how they were
# confirmed (two are the game's own terminology, two are ours).
SPECIAL_UNIT_CATEGORY = {
    0: "Standard",
    1: "Rotating bonus-pick",
    2: "Experimental",
    3: "Combat-spawned",
}

def special_unit_category(special_unit):
    """Human-readable label for a raw CardData.specialUnit value."""
    if special_unit is None:
        return "Unknown (no card data)"
    return SPECIAL_UNIT_CATEGORY.get(special_unit, f"Unknown ({special_unit})")


# All SkillData subclasses that can be a unit's mainSkillID. They all share
# SkillData's base fields (attackRange, attackDuration, splashRange, ...).
SKILL_LIST_FIELDS = [
    "skillDatas", "projectileSkillDatas", "laserSkillDatas", "aroundSkillData",
    "controllBeamSkillDatas", "rocketPunchSkillDatas", "explosionSkillDatas",
    "supportSkillDatas", "sweepSkillDatas", "trapSkillDatas",
]

# The four tech-tree upgrade cards the companion page models, as
# GameRiver.BlueprintData term keys -- see NOTES.md "Upgrade button text".
UPGRADE_TERM_KEYS = {
    "atk1": "ConfigData/BlueprintData/name_4",
    "atk2": "ConfigData/BlueprintData/name_401",
    "hp1": "ConfigData/BlueprintData/name_5",
    "hp2": "ConfigData/BlueprintData/name_501",
}

# Native-language display names for the language picker -- see NOTES.md
# "Language picker labels".
LANGUAGE_SELF_TERM = {
    "en": "Language/English", "ru": "Language/Russian", "fr": "Language/French",
    "de": "Language/German", "ko": "Language/Korean", "ja": "Language/Japanese",
    "pl": "Language/Polish", "es-ES": "Language/Spanish", "es-US": "Language/Spanish",
}
SPANISH_REGION_SUFFIX = {"es-ES": " (España)", "es-US": " (Latinoamérica)"}


def fixed_point(value):
    """Decode an FPoint (Q32.32 fixed-point value used for deterministic sim).

    Rounded to 4 decimal places: the raw division leaves binary-float noise
    (e.g. 0.5999999998603016) since most fixed-point values used here are
    round decimals at design time (0.6, 1.5, ...).
    """
    if value is None:
        return None
    return round(value["m_rawValue"] / (2**32), 4)


def fix_node_sizes(nodes):
    """TypeTreeGeneratorAPI's JSON only carries m_Type/m_Name/m_Level/m_MetaFlag;
    UnityPy's pure-Python reader also wants m_ByteSize to know primitive widths."""
    for node in nodes.traverse():
        node.m_ByteSize = PRIMITIVE_SIZES.get(node.m_Type, -1)
        if node.m_MetaFlag is None:
            node.m_MetaFlag = 0
    return nodes


def data_dir(game_root):
    return os.path.join(game_root, "Mechabellum.app", "Contents", "Resources", "Data")


def get_thin_game_assembly(game_root, cache_dir):
    """IL2CppDumper / TypeTreeGeneratorAPI want a single-architecture Mach-O,
    but GameAssembly.dylib ships as a universal (fat) binary. Thin it once
    and cache the result."""
    fat_path = os.path.join(game_root, "Mechabellum.app", "Contents", "Frameworks", "GameAssembly.dylib")
    os.makedirs(cache_dir, exist_ok=True)
    thin_path = os.path.join(cache_dir, "GameAssembly.thin.dylib")

    fat_mtime = os.path.getmtime(fat_path)
    if os.path.exists(thin_path) and os.path.getmtime(thin_path) >= fat_mtime:
        return thin_path

    arch = subprocess.check_output(["uname", "-m"]).decode().strip()
    arch = "arm64" if arch == "arm64" else "x86_64"
    subprocess.run(["lipo", "-thin", arch, fat_path, "-output", thin_path], check=True)
    return thin_path


def get_unity_version(game_root):
    """Read the Unity engine version straight from the game's own asset
    header rather than hardcoding it, so this keeps working across engine
    upgrades too."""
    env = UnityPy.load(os.path.join(data_dir(game_root), "globalgamemanagers.assets"))
    return str(env.file.unity_version)


def build_generator(game_root, cache_dir):
    ga_path = get_thin_game_assembly(game_root, cache_dir)
    metadata_path = os.path.join(data_dir(game_root), "il2cpp_data", "Metadata", "global-metadata.dat")

    gen = TypeTreeGenerator(get_unity_version(game_root))
    with open(ga_path, "rb") as f:
        ga_raw = f.read()
    with open(metadata_path, "rb") as f:
        gm_raw = f.read()
    gen.load_il2cpp(ga_raw, gm_raw)
    return gen


def generate_nodes(gen, assembly, fullname):
    nodes_json = gen.get_nodes_as_json(assembly, fullname)
    return fix_node_sizes(TypeTreeNode.from_list(json.loads(nodes_json)))


def find_monoscript_path_id(game_root, class_name):
    """MonoScript assets (one per C# class) live in globalgamemanagers.assets."""
    env = UnityPy.load(os.path.join(data_dir(game_root), "globalgamemanagers.assets"))
    for obj in env.objects:
        if obj.type.name != "MonoScript":
            continue
        if obj.read().m_ClassName == class_name:
            return obj.path_id
    raise LookupError(f"MonoScript for {class_name!r} not found")


def find_monobehaviour_instance(game_root, class_name, search_files=("level0",)):
    """Find the MonoBehaviour object whose m_Script points at `class_name`.

    We only search a short list of likely files (the boot scene, by
    default) since scanning every asset file in the install is slow and
    these config containers are always baked into level0.
    """
    script_path_id = find_monoscript_path_id(game_root, class_name)

    for fname in search_files:
        path = os.path.join(data_dir(game_root), fname)
        if not os.path.exists(path):
            continue
        env = UnityPy.load(path)
        sf = env.file
        target_fileid = None
        for i, ext in enumerate(sf.externals):
            if "globalgamemanagers.assets" in str(ext.path):
                target_fileid = i + 1
                break
        if target_fileid is None:
            continue
        for obj in sf.objects.values():
            if obj.type.name != "MonoBehaviour":
                continue
            head = obj.parse_monobehaviour_head()
            if head.m_Script.file_id == target_fileid and head.m_Script.path_id == script_path_id:
                return path, obj.path_id

    raise LookupError(f"No MonoBehaviour instance found for {class_name!r} in {search_files}")


def parse_object(path, path_id, nodes, check_read=False):
    env = UnityPy.load(path)
    for obj in env.objects:
        if obj.path_id == path_id:
            return obj.read_typetree(nodes=nodes, check_read=check_read)
    raise LookupError(f"path_id {path_id} not found in {path}")


# --- Localization -----------------------------------------------------------
#
# We deliberately don't fully parse I2Loc's giant mTerms array through the
# generic TypeTree machinery: it's thousands of records and we only need a
# handful of term keys. Instead we do a small, targeted binary read anchored
# on the term key string, whose on-disk layout we've verified by hand:
#   Term(string) -> TermType(int32) -> Languages(string[]), English is index 0.

def _read_len_string(data, pos):
    (length,) = struct.unpack_from("<i", data, pos)
    pos += 4
    s = data[pos:pos + length].decode("utf-8")
    pos += length
    pos += (-pos) % 4  # Unity string fields are 4-byte aligned
    return s, pos


def get_localized_names(resources_assets_bytes, term_key):
    """All translations for a term key, in the game's fixed language order
    (see find_language_list) -- e.g. index 0 is always English."""
    key_bytes = term_key.encode()
    needle = struct.pack("<i", len(key_bytes)) + key_bytes
    idx = resources_assets_bytes.find(needle)
    if idx == -1:
        return None
    pos = idx + len(needle)
    pos += (-pos) % 4
    pos += 4  # TermType (int32), unused
    (num_langs,) = struct.unpack_from("<i", resources_assets_bytes, pos)
    pos += 4
    names = []
    for _ in range(num_langs):
        s, pos = _read_len_string(resources_assets_bytes, pos)
        names.append(s)
    return names


def find_language_list(resources_assets_bytes):
    """The game's I2 Localization language list (name + code, in the same
    fixed order get_localized_names returns translations in), read from the
    LanguageSourceData's mLanguages field.

    Anchored on an English mLanguages entry (name "English", code "en")
    rather than a hardcoded language count, so this keeps working if the
    game adds a language. Just anchoring on the string "English" isn't
    specific enough -- the game also has a "Language/English" *term* (a
    per-language translation of the word "English" itself, for a settings
    menu) whose data happens to parse as a plausible-but-wrong language
    list, since every term has the same language count. Requiring the
    two-letter code "en" right after rules that false match out, since the
    term's translations are full words, not a code.
    """
    needle = b"English\x00" + struct.pack("<i", 2) + b"en"
    idx = resources_assets_bytes.find(needle)
    if idx == -1:
        raise LookupError('language list anchor ("English"/"en") not found')
    name_start = idx - 4  # back up over "English"'s own length prefix
    (num_langs,) = struct.unpack_from("<i", resources_assets_bytes, name_start - 4)
    pos = name_start
    languages = []
    for _ in range(num_langs):
        name, pos = _read_len_string(resources_assets_bytes, pos)
        code, pos = _read_len_string(resources_assets_bytes, pos)
        pos += 1  # Flags (bool)
        pos += (-pos) % 4
        languages.append({"name": name, "code": code})
    return languages


def resolve_native_language_names(languages, resources_assets_bytes):
    """Replace find_language_list's English label for each language (e.g.
    "Russian") with what that language calls itself (e.g. "Русский"), for
    the page's language picker. See NOTES.md "Language picker labels"."""
    for i, lang in enumerate(languages):
        code = lang["code"]
        if code in ("zh-CN", "zh-TW"):
            continue  # already a proper native name (简体中文 / 繁体中文)
        term_key = LANGUAGE_SELF_TERM.get(code)
        if term_key is None:
            continue
        names = get_localized_names(resources_assets_bytes, term_key)
        if names is None or i >= len(names):
            continue
        lang["name"] = names[i] + SPANISH_REGION_SUFFIX.get(code, "")
    return languages


def unit_sort_key(unit):
    """The game's own unlock/modification-screen order (CardData.sort) --
    unique and total for the standard roster. Non-standard cards
    (Experimental/spawned/rotating) all share sort == 0, since they aren't
    slotted into that progression; for those, fall back to cost then id."""
    sort = unit["sort"] or 0
    return (sort, unit["cost"] or 0, unit["id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", default=DEFAULT_GAME_ROOT, help="Path to the Mechabellum install directory")
    parser.add_argument("--out", default="units_data.json", help="Output JSON path")
    args = parser.parse_args()

    game_root = args.game_root
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "extracted")

    print("Reconstructing type info from the game's compiled code...", file=sys.stderr)
    gen = build_generator(game_root, cache_dir)

    # ConfigDataContainer has ~60 List<...> fields; we only need the first
    # two (cardDatas, mechDatas). We truncate the node list right after
    # mechDatas: read_value() only reads as many top-level fields as it's
    # given, and this sidesteps classes later in the struct whose TypeTree
    # the generator produces subtly wrong (unrelated to anything we need).
    raw_config_nodes = json.loads(gen.get_nodes_as_json("GRCore", "GameRiver.ConfigDataContainer"))
    level1_indices = [i for i, n in enumerate(raw_config_nodes) if n["m_Level"] == 1]
    mech_datas_pos = next(i for i in level1_indices if raw_config_nodes[i]["m_Name"] == "mechDatas")
    cutoff = next(i for i in level1_indices if i > mech_datas_pos)
    config_nodes = fix_node_sizes(TypeTreeNode.from_list(raw_config_nodes[:cutoff]))

    skill_nodes = generate_nodes(gen, "GRCore", "GameRiver.MechSkillGroupData")

    print("Locating ConfigDataContainer (unit + card stats)...", file=sys.stderr)
    cdc_path, cdc_path_id = find_monobehaviour_instance(game_root, "ConfigDataContainer")

    # check_read=False here: we deliberately truncated the node list (see
    # above), so the byte count will never match the object's real size.
    # That means a schema-vs-bytes mismatch inside blueprints/gameRules/...
    # (the fields we skip) can't raise -- so we validate structurally
    # instead, on the fields we actually use.
    cdc = parse_object(cdc_path, cdc_path_id, config_nodes, check_read=False)
    mech_datas = cdc["mechDatas"]
    card_datas = cdc["cardDatas"]

    mech_ids = [m["id"] for m in mech_datas]
    assert len(mech_ids) == len(set(mech_ids)), "duplicate mechData ids -- schema likely misaligned"
    assert len(card_datas) == len(mech_datas), (
        f"cardDatas ({len(card_datas)}) / mechDatas ({len(mech_datas)}) count mismatch -- schema likely misaligned"
    )
    for m in mech_datas:
        assert m["life"] > 0 and m["damage"] >= 0 and 0 < len(m["name"]) < 50, (
            f"implausible mechData values for id={m['id']}: life={m['life']} damage={m['damage']} "
            f"name={m['name']!r} -- schema likely misaligned"
        )

    card_by_mech_id = {c["mechID"]: c for c in card_datas}
    print(f"  -> {len(mech_datas)} mechDatas, {len(card_datas)} cardDatas", file=sys.stderr)

    print("Locating MechSkillGroupData (weapon/range/interval stats)...", file=sys.stderr)
    skill_path, skill_path_id = find_monobehaviour_instance(game_root, "MechSkillGroupData")
    # skill_nodes covers every field of the class (trapSkillDatas is the
    # last one), so this read is checked byte-exact: if the reconstructed
    # schema silently drifted from the real layout, this raises instead of
    # producing plausible-looking wrong numbers.
    skill_group = parse_object(skill_path, skill_path_id, skill_nodes, check_read=True)
    skills_by_id = {}
    for field in SKILL_LIST_FIELDS:
        for s in skill_group.get(field, []):
            skills_by_id[s["id"]] = s
    print(f"  -> {len(skills_by_id)} total skills across {len(SKILL_LIST_FIELDS)} skill types", file=sys.stderr)

    print("Loading localization data...", file=sys.stderr)
    with open(os.path.join(data_dir(game_root), "resources.assets"), "rb") as f:
        resources_bytes = f.read()
    languages = resolve_native_language_names(find_language_list(resources_bytes), resources_bytes)
    num_langs = len(languages)

    # See NOTES.md "Damage ramp" -- a few laser-type weapons deal a small
    # fraction of ATK on the first hit against a target and ramp up per
    # consecutive hit via this fixed lookup table, capping once it's
    # exhausted. This is the game's own table, not a fitted curve.
    def ramp_multipliers(skill):
        dm = skill.get("damageMultiplier") if skill else None
        if not dm:
            return None
        try:
            values = [fixed_point(x) for x in dm]
        except (TypeError, KeyError):
            return None  # a same-named field on a non-laser skill subtype, not an FPoint[]
        return values if len(set(values)) > 1 else None

    units = []
    for m in mech_datas:
        mech_id = m["id"]
        card = card_by_mech_id.get(mech_id)
        skill = skills_by_id.get(m["mainSkillID"])

        names = get_localized_names(resources_bytes, f"ConfigData/MechData/name_{mech_id}")
        if names is None or len(names) != num_langs:
            names = [m.get("name")] * num_langs  # fall back to the raw (Chinese) name for every locale

        can_ground = bool(skill["canAttackGround"]) if skill else None
        can_air = bool(skill["canAttackAir"]) if skill else None
        if can_ground is None:
            target = None
        elif can_ground and can_air:
            target = "Air & Ground"
        elif can_air:
            target = "Air Only"
        elif can_ground:
            target = "Ground Only"
        else:
            target = "None"

        units.append({
            "id": mech_id,
            "names": names,
            "specialUnit": card["specialUnit"] if card else None,
            "testUnit": bool(card["isTestUnit"]) if card else None,
            "category": special_unit_category(card["specialUnit"] if card else None),
            "cost": card["baseMoney"] if card else None,
            "hp": m["life"],
            "atk": m["damage"],
            "speedMps": m["moveSpeed"],
            "rangeM": fixed_point(skill["attackRange"]) if skill else None,
            "attackInterval": fixed_point(skill["attackDuration"]) if skill else None,
            "splashRangeM": fixed_point(skill["splashRange"]) if skill else None,
            "target": target,
            "flying": bool(m["isFly"]),
            "rampMultipliers": ramp_multipliers(skill),
            "combatSize": UNIT_TYPE_NAMES.get(m["mechType"], m["mechType"]),
            "moveType": MOVE_TYPE_NAMES.get(m["moveType"], m["moveType"]),
            "unitsPerCard": card["mechCount"] if card else None,
            # Unlock-cost tier: 1-4 for standard roster cards (correlates
            # with size -- 1=free tier, 2=intermediate, 3=Giant, 4=Titan),
            # 0 for non-standard cards (Experimental/spawned/rotating --
            # these aren't slotted into the group progression).
            "group": card["group"] if card else None,
            "unlockPrice": card["unlockPrice"] if card else None,
            # The game's own sort key for the unit unlock/modification
            # screens -- see unit_sort_key.
            "sort": card["sort"] if card else None,
            # Deployment footprint size. Not officially documented, but it
            # scales cleanly with cost/group (e.g. 6-8 for the cheapest
            # units, up to 70 for Titans), which is the closest thing to a
            # "tile count" figure in the data.
            "slotSize": card["slotSize"] if card else None,
            # Card portrait/UI dimensions, NOT a battlefield footprint --
            # these are Vector2 sizes for how big the card graphic renders
            # in menus, kept here for completeness.
            "cardWidth": fixed_point(card["cardBaseSize"]["x"]) if card else None,
            "cardHeight": fixed_point(card["cardBaseSize"]["y"]) if card else None,
        })

    units.sort(key=unit_sort_key)

    upgrade_terms = {}
    for key, term_key in UPGRADE_TERM_KEYS.items():
        names = get_localized_names(resources_bytes, term_key)
        if names is None or len(names) != num_langs:
            raise LookupError(f"couldn't resolve {term_key!r} in every language")
        upgrade_terms[key] = names

    payload = {"languages": languages, "upgradeTerms": upgrade_terms, "units": units}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(units)} units in {num_langs} languages to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
