"""Which published perfumes belong together, worked out from the data alone (nothing voted, nothing guessed):

- versions: the same line from one house, such as flankers and other concentrations ("Stronger With You",
  "… Absolutely", "… Intensely"; Sauvage EDT and Sauvage Parfum). Two perfumes are one line when one name, without
  brand and filler words, is the other's name with words added at the end (or the same name).
- similar: perfumes of other lines that share confirmed notes and main accords. A precise note also counts a little
  for its general one (pink pepper for pepper), so close cousins still match.

pages.index calls lines() and similar() once per catalog change; a page only reads the result.
"""
import math
from collections import defaultdict

import accords
import catalog

TIER_W = {"top": 0.8, "heart": 1.0, "base": 1.2}   # the dry-down is what you smell longest
PARENT_W = 0.5        # how much "pink pepper" counts for "pepper"
NOTES_SHARE = 0.65    # the rest is the main accords
MIN_SCORE = 0.30      # below this two perfumes aren't shown as similar
MIN_SHARED = 2        # confirmed notes (or a note and its general form) they must have in common
MAX_LINE = 8         # a "line" bigger than this is a collection (Prada Olfactories: 11 perfumes) or a naming accident
SHOW = 6


def _line_key(p):
    """The name as a key without brand words, filler and a trailing gender word ("Le Male Pour Homme" = "le male")."""
    bk = catalog.brand_key(p["brand"])
    nk, _ = catalog.gender_tail(catalog.name_key(p["name"], bk))
    return bk, nk


def lines(perfumes):
    """{id: [ids of the other versions]}, nearest first (same name before longer names)."""
    by_brand = defaultdict(list)
    for p in perfumes:
        bk, nk = _line_key(p)
        if nk:
            by_brand[bk].append((nk, p))
    out = {}
    for items in by_brand.values():
        parent = {p["id"]: p["id"] for _, p in items}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for a, pa in items:
            for b, pb in items:
                if pa["id"] != pb["id"] and (a == b or b.startswith(a + " ")):
                    parent[find(pb["id"])] = find(pa["id"])
        groups = defaultdict(list)
        for nk, p in items:
            groups[find(p["id"])].append((nk, p))
        for g in groups.values():
            if len(g) < 2 or len(g) > MAX_LINE:
                continue
            for nk, p in g:
                others = sorted((x for x in g if x[1]["id"] != p["id"]),
                                key=lambda x: (x[0] != nk, len(x[0]), x[1]["name"], x[1].get("conc") or ""))
                out[p["id"]] = [x[1]["id"] for x in others]
    return out


def note_vector(p):
    """{note: weight} of the confirmed, known notes, plus a smaller weight for each one's general note."""
    v = defaultdict(float)
    for tier, w in TIER_W.items():
        for n in p.get("notes", {}).get(tier, []):
            k = n.get("en")
            if not k or not n.get("confirmed"):
                continue
            v[k] = max(v[k], w)
            g = catalog.parent_of(k, catalog.NOTE_EN)
            if g and g != k:
                v[g] = max(v[g], w * PARENT_W)
    return dict(v)


def _cos(a, b):
    dot = sum(x * b[k] for k, x in a.items() if k in b)
    if not dot:
        return 0.0
    return dot / (math.sqrt(sum(x * x for x in a.values())) * math.sqrt(sum(x * x for x in b.values())))


def similar(perfumes, versions=None):
    """{id: [(other id, score 0-1, [shared notes])]} best first, without the perfume's own line."""
    versions = versions if versions is not None else lines(perfumes)
    vecs = {p["id"]: note_vector(p) for p in perfumes}
    accs = {p["id"]: dict(accords.main_accords(p)) for p in perfumes}
    own = {p["id"]: {k for k, w in vecs[p["id"]].items() if w >= min(TIER_W.values())} for p in perfumes}
    out = {}
    for p in perfumes:
        i, same = p["id"], set(versions.get(p["id"], ()))
        found = []
        for q in perfumes:
            j = q["id"]
            if j == i or j in same:
                continue
            shared = own[i] & own[j]
            # A note of one and its general form in the other ("pink pepper" / "pepper") count as shared too.
            near = {k for k in set(vecs[i]) & set(vecs[j]) if k not in shared}
            if len(shared) + 0.5 * len(near) < MIN_SHARED:
                continue
            score = NOTES_SHARE * _cos(vecs[i], vecs[j]) + (1 - NOTES_SHARE) * _cos(accs[i], accs[j])
            if score >= MIN_SCORE:
                found.append((j, round(score, 3), sorted(shared, key=lambda k: -vecs[i][k] - vecs[j][k])))
        found.sort(key=lambda x: (-x[1], x[0]))
        out[i] = found[:SHOW]
    return out
