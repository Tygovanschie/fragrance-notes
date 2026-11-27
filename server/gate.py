"""The check between the catalog and the website: nothing changes on a page until it has passed.

catalog.build makes the catalog from what shops show, every hour. gate.run (right after it) decides what the website
shows; pages.index reads only the published table this keeps.

- A published perfume that only grows (more shops, more confirmed notes) is updated by itself.
- A change that could be a mistake is held: another name or brand, another concentration, men <-> women, a confirmed
  note that disappears, or the perfume disappearing altogether. The page keeps its last approved version and the
  change waits on the review page (step 1).
- A new perfume only gets a page when nothing about it looks wrong: no leftovers of a shop's title in its name, no
  packaging or non-perfume words, sources that agree (catalog's own review list), notes that look like notes (step 3).
  A brand's own creative note names ("Nylon Accord") are fine: they just get no note page.
- If one rebuild would hold far more than usual, or would lose many pages, nothing is updated at all until Tygo
  approves that rebuild (step 2, the safety brake): a mistake in the code can't reach the website by itself.
- A name the nightly job cleaned (maintenance.name_fixes, words removed only) is used when it passes the same checks
  (step 4).
- Decisions on the review page (approve / reject) are kept per perfume and value and applied at every run, so the same
  question never comes back (step 5).
Only perfume data: nothing about visitors or users.
"""
import json
import os
import re
import sqlite3
import time

import catalog
import maintenance

PAGE_MIN_CONFIRMED = int(os.environ.get("PAGE_MIN_CONFIRMED", "3"))   # as in pages.py
BRAKE_HOLDS = int(os.environ.get("GATE_BRAKE_HOLDS", "10"))     # new holds on published pages in one run
BRAKE_LOSS = float(os.environ.get("GATE_BRAKE_LOSS", "0.05"))    # share of published pages that would go
BRAKE_PASS = 3 * 3600   # an approved brake lets rebuilds through for this long

SCHEMA = """
CREATE TABLE IF NOT EXISTS published (id TEXT PRIMARY KEY, data TEXT NOT NULL, since INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS gate_review (id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, detail TEXT NOT NULL,
    first INTEGER NOT NULL, PRIMARY KEY (id, kind));
CREATE TABLE IF NOT EXISTS gate_decision (id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
    decision TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (id, kind, value));
CREATE TABLE IF NOT EXISTS gate_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

# What the review page calls each kind of held item.
KINDS = {"new": "New perfume", "name": "Name changes", "brand": "Brand changes", "conc": "Concentration changes",
         "gender": "Men/women changes", "notes": "Confirmed notes disappear", "gone": "Page would disappear",
         "brake": "Safety brake"}

# ---------- checks ----------

# Words that mean the product isn't the perfume itself, or a pack of it.
NOT_PERFUME = re.compile(r"\b(tester|samples?|miniatures?|mini|gift ?sets?|giftset|coffret|set|refill|navulling|travel|"
                         r"deo|deodorants?|deodorant stick|lotion|shower|gel|douchegel|body ?milk|body ?cream|creme|cream|"
                         r"soap|zeep|candle|kaars|hair ?mist|aftershave balm|balm)\b", re.I)


def name_problems(name, brand=""):
    """What looks wrong in a perfume's displayed name ([] when nothing)."""
    out = []
    n = str(name or "").strip()
    if not re.search(r"\w", n):
        return ["no name"]
    if re.search(r"[()\[\]{}|]", n):
        out.append("brackets or | in the name")
    if re.search(r"\s[-–—]\s|^[-–—]|[-–—]$", n):
        out.append("loose dash in the name")
    if re.search(r"\d+(?:[.,]\d+)?\s?(ml|fl\.? ?oz|oz)\b", n, re.I):
        out.append("a size in the name")
    if NOT_PERFUME.search(n):
        out.append("a packaging or non-perfume word (" + NOT_PERFUME.search(n).group(0) + ")")
    if catalog.shouting(n):
        out.append("written in capitals")
    if brand and catalog.plain(n) == catalog.plain(brand):
        out.append("the name is only the brand")
    if len(n) > 70:
        out.append("very long name")
    return out


def note_problems(p):
    bad = [x["name"] for t in p["notes"].values() for x in t
           if x.get("confirmed") and (re.search(r"\d|https?:|www\.|@", x["name"]) or len(x["name"]) > 40)]
    return [f"odd note names: {', '.join(bad[:3])}"] if bad else []


def new_problems(p):
    """Why a perfume shouldn't get its first page by itself ([] when it can)."""
    return name_problems(p["name"], p["brand"]) + list(p.get("review") or []) + note_problems(p)


def confirmed_notes(p):
    """The confirmed notes as today's dictionary reads them: a note the dictionary has since learned ("Nylon Accord"
    -> nylon, "Oak Wood" -> oak) is the same note, not a lost one."""
    return {catalog.note_key(x["name"]) or x.get("en") or catalog.plain(x["name"])
            for t in p["notes"].values() for x in t if x.get("confirmed")}


def lost_notes(old, new):
    """Confirmed notes of `old` that `new` doesn't have, leaving out a general note that merged into its more precise
    form (blackcurrant -> blackcurrant bud: see catalog.merge_notes)."""
    now = confirmed_notes(new)
    return sorted(n for n in confirmed_notes(old) - now if not any(catalog.parent_of(c, {n}) == n for c in now))


def changes(old, new):
    """[(kind, value, detail)]: what changed on a published perfume that could be a mistake."""
    out, who = [], f'{old["brand"]} {old["name"]}'
    if catalog.plain(old["name"]) != catalog.plain(new["name"]):
        out.append(("name", new["name"], f'{old["brand"]}: “{old["name"]}” would become “{new["name"]}”'))
    if catalog.brand_key(old["brand"]) != catalog.brand_key(new["brand"]):
        out.append(("brand", new["brand"], f'{who}: brand “{old["brand"]}” would become “{new["brand"]}”'))
    if old.get("conc") and old.get("conc") != new.get("conc"):
        out.append(("conc", new.get("conc") or "", f'{who}: {old["conc"]} would become {new.get("conc") or "unknown"}'))
    if {old.get("gender"), new.get("gender")} == {"m", "f"}:
        out.append(("gender", new["gender"], f'{who}: for {"men" if old["gender"] == "m" else "women"} would become '
                                             f'for {"men" if new["gender"] == "m" else "women"}'))
    lost = lost_notes(old, new)
    if lost:
        out.append(("notes", ", ".join(lost), f'{who}: would lose the confirmed note(s) {", ".join(lost)}'))
    return out


def deletion_only(before, after):
    """True when `after` is `before` with whole words left out (and at least one real word left): the only kind of
    name change the nightly job may make by itself."""
    a, b = catalog.plain(before).split(), catalog.plain(after).split()
    if not b or len(b) >= len(a):
        return False
    it = iter(a)
    return all(w in it for w in b)


def keep_words(original, clean):
    """The original name with only the words left that `clean` keeps, in the original's own spelling (accents,
    capitals): a model's answer can leave words out, but never change or add one. '' when `clean` isn't that."""
    want = catalog.plain(clean).split()
    out = []
    for w in str(original).split():
        p = catalog.plain(w).split()
        if p and want[:len(p)] == p:
            out.append(w)
            want = want[len(p):]
    if want or not out:
        return ""
    return " ".join(" ".join(out).split()).strip(" -–—:,|/·()[]")


# ---------- the run ----------

def init(con):
    con.executescript(SCHEMA)


def meta(con, k, default=None):
    r = con.execute("SELECT v FROM gate_meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def set_meta(con, k, v):
    con.execute("INSERT OR REPLACE INTO gate_meta (k, v) VALUES (?, ?)", (k, str(v)))


def candidates(con, fixes=None):
    """The perfumes in the catalog with enough confirmed notes for a page, as pages show them."""
    con.row_factory = sqlite3.Row
    out = {}
    for r in con.execute("SELECT * FROM catalog WHERE confirmed >= ?", (PAGE_MIN_CONFIRMED,)):
        p = catalog.row_out(r, full=True)
        p["review"] = json.loads(r["review"] or "[]")
        fix = (fixes or {}).get(p["id"])
        if fix and deletion_only(p["name"], fix) and not name_problems(fix, p["brand"]):
            p["name"], p["nameFrom"] = fix, p["name"]
        out[p["id"]] = p
    return out


def run(con, now=None, fixes=None):
    """Decide what the website shows after a catalog rebuild. Returns a one-line summary."""
    now = int(now or time.time())
    init(con)
    fixes = maintenance.name_fixes() if fixes is None else fixes
    cur = candidates(con, fixes)
    pub = {r[0]: json.loads(r[1]) for r in con.execute("SELECT id, data FROM published")}
    dec = {(r[0], r[1], r[2]): r[3] for r in con.execute("SELECT id, kind, value, decision FROM gate_decision")}
    before = {(r[0], r[1]) for r in con.execute("SELECT id, kind FROM gate_review")}
    if meta(con, "seeded") is None:   # the first run: everything that is online now stays online
        with con:
            con.executemany("INSERT OR REPLACE INTO published (id, data, since) VALUES (?,?,?)",
                            [(i, json.dumps(p, ensure_ascii=False), now) for i, p in cur.items()])
            set_meta(con, "seeded", now)
            set_meta(con, "version", now)
        return f"gate: first run, {len(cur)} pages published as they are"

    show, held = {}, []   # held: (id, kind, value, detail)
    for i, p in cur.items():
        old = pub.get(i)
        if old is None:
            probs = new_problems(p)
            if not probs:
                show[i] = p
                continue
            value = p["name"] + " | " + "; ".join(probs)
            d = dec.get((i, "new", value))
            if d == "approve":
                show[i] = p
            elif d != "reject":
                held.append((i, "new", value, f'{p["brand"]} {p["name"]}: {"; ".join(probs)}'))
            continue
        open_ = [(k, v, t) for k, v, t in changes(old, p) if dec.get((i, k, v)) != "approve"]
        show[i] = old if open_ else p
        held += [(i, k, v, t) for k, v, t in open_ if dec.get((i, k, v)) != "reject"]
    for i, old in pub.items():
        if i in cur:
            continue
        # Merged into a perfume of the same house and concentration that has a page: the old address redirects
        # there (catalog.moved_to), so nothing is lost and nothing needs a person.
        new = catalog.moved_to(con, i)
        if new and new in cur and catalog.brand_key(cur[new]["brand"]) == catalog.brand_key(old["brand"]) \
                and (cur[new].get("conc") or "") == (old.get("conc") or ""):
            continue
        d = dec.get((i, "gone", ""))
        if d != "approve":
            show[i] = old
            if d != "reject":
                held.append((i, "gone", "", f'{old["brand"]} {old["name"]}: no longer has {PAGE_MIN_CONFIRMED} confirmed '
                                            f'notes in the catalog, or was merged into another perfume'))

    # The safety brake: far more new holds on published pages than usual, or many pages that would go.
    fresh = [h for h in held if h[1] != "new" and (h[0], h[1]) not in before]
    losing = sum(1 for h in held if h[1] == "gone")
    reason = ""
    if len(fresh) > BRAKE_HOLDS:
        reason = f"{len(fresh)} published pages would change at once"
    elif pub and len(pub) >= 20 and losing > BRAKE_LOSS * len(pub):
        reason = f"{losing} of {len(pub)} published pages would disappear"
    # Once on, the brake stays on (also when the next rebuild looks normal) until Tygo approves it on the review page.
    reason = reason or meta(con, "brake") or ""
    if reason and now < int(meta(con, "brake_pass", 0)):
        reason = ""   # Tygo approved a braked rebuild less than BRAKE_PASS ago
    with con:
        if reason:
            set_meta(con, "brake", reason)
            con.execute("INSERT OR IGNORE INTO gate_review (id, kind, value, detail, first) VALUES ('*','brake','',?,?)",
                        (f"Nothing was updated on the website: {reason}. Approve if these changes are right "
                         f"(the items are listed below), reject to keep everything as it is.", now))
            for i, k, v, t in held:
                con.execute("INSERT OR IGNORE INTO gate_review (id, kind, value, detail, first) VALUES (?,?,?,?,?)",
                            (i, k, v, t, now))
            return f"gate: BRAKE, nothing published ({reason})"
        con.execute("DELETE FROM gate_meta WHERE k='brake'")
        firsts = {(r[0], r[1]): r[2] for r in con.execute("SELECT id, kind, first FROM gate_review")}
        con.execute("DELETE FROM gate_review")
        con.executemany("INSERT INTO gate_review (id, kind, value, detail, first) VALUES (?,?,?,?,?)",
                        [(i, k, v, t, firsts.get((i, k), now)) for i, k, v, t in held])
        changed = 0
        for i, p in show.items():
            if pub.get(i) != p:
                con.execute("INSERT OR REPLACE INTO published (id, data, since) VALUES (?,?,?)",
                            (i, json.dumps(p, ensure_ascii=False), now))
                changed += 1
        gone = [i for i in pub if i not in show]
        con.executemany("DELETE FROM published WHERE id=?", [(i,) for i in gone])
        if changed or gone:
            set_meta(con, "version", now)
    new = sum(1 for i in show if i not in pub)
    return f"gate: {len(show)} pages ({new} new, {changed - new} updated, {len(gone)} removed), {len(held)} waiting for review"


def published(con):
    """The published perfumes, or None before the gate's first run (then pages use the catalog as before)."""
    try:
        if meta(con, "seeded") is None:
            return None
        return [json.loads(r[0]) for r in con.execute("SELECT data FROM published")]
    except sqlite3.OperationalError:
        return None


def version(con):
    try:
        return meta(con, "version")
    except sqlite3.OperationalError:
        return None


# ---------- decisions (the review page) ----------

def open_items(con):
    try:
        rows = con.execute("SELECT id, kind, value, detail, first FROM gate_review ORDER BY kind='brake' DESC, first, id").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(zip(("id", "kind", "value", "detail", "first"), r)) for r in rows]


def decide(con, pid, kind, value, decision, now=None):
    """Store Tygo's decision on a held item and apply it right away. False if there is no such open item."""
    if decision not in ("approve", "reject"):
        return False
    init(con)
    row = con.execute("SELECT value FROM gate_review WHERE id=? AND kind=?", (pid, kind)).fetchone()
    if not row or row[0] != value:
        return False
    now = int(now or time.time())
    with con:
        if kind == "brake":   # only approving does something: until then nothing changes on the website
            if decision != "approve":
                return True
            con.execute("DELETE FROM gate_review WHERE id='*' AND kind='brake'")
            con.execute("DELETE FROM gate_meta WHERE k='brake'")
            set_meta(con, "brake_pass", now + BRAKE_PASS)
        else:
            con.execute("INSERT OR REPLACE INTO gate_decision (id, kind, value, decision, day) VALUES (?,?,?,?,date('now'))",
                        (pid, kind, value, decision))
    run(con, now)
    return True


def status(con):
    try:
        return {"brake": meta(con, "brake"), "waiting": con.execute("SELECT COUNT(*) FROM gate_review").fetchone()[0]}
    except sqlite3.OperationalError:
        return {"brake": None, "waiting": 0}
