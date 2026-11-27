#!/usr/bin/env python3
"""Nightly maintenance with the local LLM (Ollama on 127.0.0.1, see ~/ollama). Runs on the host (cron), like backup.py.

Six jobs, each writing a list to review/. Since 2026-11-25 two of them also fix things themselves, but only where a
mistake is unlikely and easy to take back; they never touch the main database or the code, only their own
data/auto.db (maintenance.py), which the API reads:
- a shop's spelling of a note becomes that known note when the model is sure AND a second question agrees (never a
  new note: the model guessed "almond wood" for "Belambra Hout");
- a note description goes online when it passes every check against its Wikipedia source.
Everything else (unknown notes, possible duplicates, possible non-perfumes, texts that failed a check) goes on the
todo list for the weekly email (GET /maintenance/week, sent by the Worker). `--undo NIGHT` takes a night back.


1. notes-DATE.md  Note names in the catalog that catalog.NOTE_WORDS doesn't know: an English name, and whether it
                  is the same as a note the dictionary has. Good ones go into NOTE_WORDS by hand.
2. obf-DATE.md    Open Beauty Facts products that are probably not a perfume (deodorant, body mist, shower gel…),
                  which came in through a perfume category tag. Good ones become a filter in obf.py.
3. names-DATE.md  (a) Perfume names with promotion or packaging words ("- Summer Deal", "Giftset", "Tester") that
                  split one perfume in two when there's no barcode; (b) pairs of perfumes of the same house that
                  are probably the same perfume under another spelling. Good ones become rules in catalog.py.

4. texts-DATE.md   Descriptions for the note pages (pages.py): the model rewrites the Wikipedia intro of the plant
                  or material, with a check for names it added. Good ones go into server/note_texts.json by hand.

5. shops-DATE.md   Shops users added themselves (domain only, opt-in), with how many installs: candidates for
                  the built-in list. No model involved.

7. (no list)      Names the gate (gate.py) held: the model may only leave words out, and the result must pass the
                  gate's own name check; it goes into auto.db name_fix (undo with --undo NIGHT), the rest to the todo list.

6. photos-DATE.md  Free bottle photos on Wikimedia Commons for published perfumes without one; good ones go into
                  server/perfume_photos.json by hand. No model involved.

What was asked before is remembered in review/seen.json, so each list only has new items.
Prints one line per job; under cron through `systemd-cat -t fragrance-llm` (journalctl -t fragrance-llm).
"""
import datetime
import json
import os
import sqlite3
import sys
import time
import re
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import catalog  # noqa: E402  (NOTE_EN, brand_key, name_key, plain)

DB = os.environ.get("DB_PATH", os.path.join(BASE, "data", "prices.db"))
OUT = os.environ.get("REVIEW_DIR", os.path.join(BASE, "review"))
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:14b")   # slower than 7b (partly on the CPU), but knows more and guesses less
MAX_ITEMS = int(os.environ.get("LLM_MAX_ITEMS", "500"))   # per job and night
DAY = datetime.date.today().isoformat()
import maintenance  # noqa: E402  (data/auto.db: what the job fixes itself)

# The job's own database (maintenance.py): set in main(). Changes there are logged per night and can be undone.
AUTO = None


def changed(kind, item, detail):
    AUTO.execute("INSERT INTO changes (night, kind, item, detail) VALUES (?,?,?,?)", (DAY, kind, str(item)[:120], str(detail)[:300]))


def todo(kind, item, detail):
    """Something the job doesn't fix itself: in the weekly email for a person to decide."""
    AUTO.execute("INSERT OR REPLACE INTO todo (night, kind, item, detail) VALUES (?,?,?,?)",
                 (DAY, kind, str(item)[:120], str(detail)[:300]))



def ask(prompt, model=None, attempt=0):
    """The model's JSON answer. attempt 0 is the steady answer (temperature 0); a later attempt asks again with some
    variation, so a note that failed a check gets a different text instead of the same one every night."""
    opts = {"temperature": 0} if not attempt else {"temperature": 0.6, "seed": attempt}
    opts["num_ctx"] = 8192   # the prompts are short; a smaller context keeps the 14b model in memory
    body = json.dumps({"model": model or MODEL, "prompt": prompt, "format": "json", "stream": False,
                       "options": opts}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:   # the bigger model is slow on this GPU, which is fine at night
        return json.loads(json.loads(r.read())["response"])


def cell(s):
    return str(s if s is not None else "").replace("|", "/").replace("\n", " ")


def write_list(name, title, intro, header, rows):
    path = os.path.join(OUT, f"{name}-{DAY}.md")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"# {title} ({DAY}, {MODEL})\n\n{intro}\n\n| " + " | ".join(header) + " |\n|"
                + "---|" * len(header) + "\n")
        for r in rows:
            f.write("| " + " | ".join(cell(c) for c in r) + " |\n")
        f.write("\n")
    os.chmod(path, 0o600)
    return path


# ---------- 1. note names ----------
NOTE_PROMPT = """You normalise perfume note names (often Dutch) for a perfume database. Be careful and honest.

Reply in JSON: {{"english": ..., "same_as": ..., "sure": ...}}
- "english": the usual English perfumery name, lowercase. Translate word by word; never replace a note by a
  different note. If the name is a brand-name aroma chemical or a word you don't know, keep it as written
  (lowercase) instead of guessing.
- "same_as": ONLY if it is exactly the same note as one in the list below (only the language or spelling
  differs), that list entry; otherwise null. A note with an extra word is a different note:
  "bourbon vanilla" is not "vanilla", "glazed chestnut" is not "chestnut", "black tea" is not "tea".
- "sure": true only if you know this note; false if you kept an unknown word.

Examples:
"Roze peper" -> {{"english": "pink pepper", "same_as": "pink pepper", "sure": true}}
"Geglazuurde kastanje" -> {{"english": "glazed chestnut", "same_as": null, "sure": true}}
"Zibetone" -> {{"english": "zibetone", "same_as": null, "sure": false}}

List: {existing}
Name: "{name}" ->"""


# A second question, the other way round, before a spelling is mapped by itself.
VERIFY_PROMPT = """Are these two perfume note names exactly the same note, only in another language or spelling?
A note with an extra word is a different note: "glazed chestnut" is not "chestnut", "bourbon vanilla" is not
"vanilla", "white musk" is not "musk", "pink pepper" is not "pepper".
Reply in JSON: {{"same": true or false}}

A: "{a}"
B: "{b}\""""

def _words(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).split()


def note_hint(name, english, existing):
    """The email line for an unknown note: the model's translation only when it differs from the name (a name that
    is already English otherwise comes back as itself), plus the known notes it is built on, so the choice is
    'new note' or 'same as a known one'."""
    eng = str(english).strip().lower()[:40]
    words = _words(eng)
    parts = ["new note? name is already English" if words == _words(name) else f"maybe {eng}"]
    known, text = [], f" {' '.join(words)} "
    for k in sorted(existing, key=len, reverse=True):
        kk = " ".join(_words(k))
        if kk and f" {kk} " in text and not any(f" {kk} " in f" {o} " for o in known):
            known.append(kk)
    if known:
        parts.append("contains known " + ", ".join(known[:3]))
    return "; ".join(parts)


def job_notes(con, seen):
    notes = {}
    for brand, name, data in con.execute("SELECT brand, name, data FROM catalog"):
        d = json.loads(data)
        for tier in ("top", "heart", "base"):
            for n in d["notes"][tier]:
                if n.get("en"):
                    continue
                u = notes.setdefault(n["key"], {"name": n["name"], "shops": 0, "perfumes": []})
                u["shops"] += n["shops"]
                if len(u["perfumes"]) < 3:
                    u["perfumes"].append(f"{brand} {name}")
    new = sorted((k for k in notes if k not in seen), key=lambda k: (-notes[k]["shops"], k))[:MAX_ITEMS]
    if not new:
        return f"notes: nothing new ({len(notes)} unknown, all asked before)", []
    existing = sorted(catalog.NOTE_EN)
    rows, fixed = [], 0
    for k in new:
        n = notes[k]
        a = ask(NOTE_PROMPT.format(existing=", ".join(existing), name=n["name"]))
        same, remark = a.get("same_as"), ""
        if same is not None and same not in existing:   # the model named a note that isn't in the list
            remark, same = f"model said same as '{same}', which the dictionary doesn't have", None
        # Fixed by itself only when the model is sure, names a note the dictionary has, and a second question asked
        # the other way round agrees. It never adds a new note: unknown ones stay for a person.
        if same and a.get("sure") is True and ask(VERIFY_PROMPT.format(a=n["name"], b=same)).get("same") is True:
            AUTO.execute("INSERT OR REPLACE INTO note_alias (word, canon, night) VALUES (?,?,?)", (k, same, DAY))
            changed("note name", n["name"], f"now read as {same} ({n['shops']} shops)")
            fixed += 1
            remark = "fixed: mapped automatically"
        elif a.get("english"):
            todo("unknown note", n["name"], f"{note_hint(n['name'], a.get('english'), existing)}; seen on {'; '.join(n['perfumes'])}")
        rows.append([n["name"], str(a.get("english") or "").strip().lower()[:60], same or "—",
                     "yes" if a.get("sure") is True else "no", n["shops"], "; ".join(n["perfumes"]), remark])
    path = write_list("notes", "Note names to review",
                      "Proposals only: nothing was changed. Add the good ones to NOTE_WORDS in server/catalog.py\n"
                      "(same_as: as a spelling of that note; otherwise as a new note), then regenerate the extension's\n"
                      "NOTE_GROUPS. Not sure = the model kept a word it doesn't know.",
                      ["Shop spelling", "English (proposal)", "Same as", "Sure", "Shops", "Seen on", "Remark"], rows)
    sure = sum(r[3] == "yes" for r in rows)
    return f"notes: {len(rows)} new names ({sure} sure, {fixed} mapped automatically) -> {path}", new


# ---------- 2. Open Beauty Facts products that aren't perfume ----------
OBF_PROMPT = """You check products from an open cosmetics database for a perfume database.
Is this product a perfume to wear (eau de parfum, eau de toilette, eau de cologne, parfum, extrait, perfume oil,
a perfume sample, a perfume gift set with the perfume in it)? Or something else, such as a deodorant, body mist or
body spray, shower gel, body lotion, hair mist, aftershave balm, room spray, candle or soap?
Most products here ARE perfumes. Answer false ONLY when the brand or the name itself says it is something else
(words like deodorant, deo, body mist, brume, body spray, perfumed body, hair mist, shower, lotion, soap, room,
candle, aftershave balm). A perfume name without such a word is a perfume, also when you don't know it, also a
small size (1-10 ml samples, perfume oils) and also without a concentration.
Reply in JSON: {{"perfume": true or false, "kind": "what it is, in 1 to 3 English words", "evidence": "the word in
the brand or name that shows it, or null", "sure": true or false}}

Product: brand "{brand}", name "{name}", concentration "{conc}", size {ml}"""


def job_obf(con, seen):
    rows_in = con.execute("SELECT code, brand, name, conc, ml FROM obf_products ORDER BY code").fetchall()
    new = [r for r in rows_in if r[0] not in seen][:MAX_ITEMS]
    if not new:
        return f"obf: nothing new ({len(rows_in)} products, all asked before)", []
    flagged = []
    for code, brand, name, conc, ml in new:
        a = ask(OBF_PROMPT.format(brand=brand, name=name, conc=conc or "unknown", ml=f"{ml:g} ml" if ml else "unknown"))
        evidence = catalog.plain(a.get("evidence") or "")
        # Only a flag the model can point to in the brand or name itself (it tends to call unknown perfumes "body mist").
        if a.get("perfume") is False and evidence and evidence in catalog.plain(f"{brand} {name}"):
            todo("not a perfume?", f"{brand} {name}", f"Open Beauty Facts {code}: the model says {str(a.get('kind') or '')[:40]}")
            flagged.append([code, brand, name, conc or "—", f"{ml:g} ml" if ml else "—",
                            str(a.get("kind") or "")[:40], "yes" if a.get("sure") is True else "no"])
    path = write_list("obf", "Open Beauty Facts products that are probably not perfume",
                      f"Proposals only: nothing was changed. {len(new)} products checked, {len(flagged)} flagged.\n"
                      "Good ones become a filter in server/obf.py (by word or by barcode).",
                      ["Barcode", "Brand", "Name", "Conc.", "Size", "Model says it is", "Sure"], flagged)
    return f"obf: {len(new)} products checked, {len(flagged)} flagged -> {path}", [r[0] for r in new]


# ---------- 3. names: promotion words, and the same perfume under two names ----------
PROMO_PROMPT = """You clean up perfume product names from web shops.
Remove only promotion and packaging words that are not part of the perfume's own name, such as "summer deal",
"sale", "aanbieding", "actie", "giftset", "gift set", "coffret", "tester", "navulling", "refill", "travel size",
"limited offer", "black friday", or a size like "100 ml". Keep the real name exactly as written, including
versions such as "Intense", "Intensely", "Elixir", "Absolu", "Le Parfum", "Pour Homme", "Night", "Sport".
Reply in JSON: {{"clean": "the name without those words", "removed": ["words you removed"]}}

Name: "{name}\""""

# Words that name a version of a perfume, not a promotion: never accepted as "promotion words" on their own.
VERSION_WORDS = {"intense", "intensely", "absolu", "absolute", "elixir", "parfum", "perfume", "extrait", "le", "la", "l",
                 "eau", "de", "black", "red", "white", "blue", "gold", "noir", "rouge", "blanc", "night", "nuit", "day",
                 "summer", "winter", "sport", "fresh", "powerfully", "pour", "homme", "femme", "for", "her", "him", "men",
                 "women", "man", "woman", "in", "full", "edition", "cologne", "toilette", "privee", "prive", "oud",
                 "pure", "extreme", "classic", "original", "s", "x", "one", "only"}

SAME_PROMPT ="""Two product names from web shops, both by the perfume house "{brand}", both {conc}.
Are they the same perfume, only written differently (other word order, an abbreviation, the house name inside
the name, a translated "for men")? Different versions are NOT the same: "Intense", "Intensely", "Elixir",
"Absolu", "Le Parfum", "Night", "Sport", "Powerfully" or another added word make it another perfume.
Reply in JSON: {{"same": true or false, "sure": true or false}}

A: "{a}"
B: "{b}\""""


def job_names(con, seen):
    perfumes = con.execute("SELECT id, brand, name, conc, gender FROM catalog").fetchall()
    # (a) promotion and packaging words
    new_names = [p for p in perfumes if "name:" + p[0] not in seen][:MAX_ITEMS]
    promo = []
    for pid, brand, name, conc, gender in new_names:
        a = ask(PROMO_PROMPT.format(name=name))
        clean = str(a.get("clean") or "").strip()
        removed = set(catalog.plain(name).split()) - set(catalog.plain(clean).split())
        # The model also strips real version names ("Intense", "Black", "Powerfully"): only keep proposals that
        # remove at least one word that isn't such a version word or a number.
        if not removed or all(w in VERSION_WORDS or w.isdigit() for w in removed):
            continue
        if catalog.plain(clean) != catalog.plain(name) and catalog.plain(clean) in catalog.plain(name):
            promo.append([brand, name, clean, ", ".join(map(str, a.get("removed") or []))[:60], pid])
            todo("shop words in name", f"{brand} {name}", f"maybe just \"{clean}\"")
    # (b) same house, same concentration (or one unknown), compatible gender, names that overlap a lot
    groups = {}
    for p in perfumes:
        groups.setdefault(catalog.brand_key(p[1]), []).append(p)
    pairs = []
    for bk, ps in groups.items():
        for i, p in enumerate(ps):
            for q in ps[i + 1:]:
                if p[3] and q[3] and p[3] != q[3]:
                    continue
                if p[4] in ("m", "f") and q[4] in ("m", "f") and p[4] != q[4]:
                    continue
                a, b = set(catalog.name_key(p[2], bk).split()), set(catalog.name_key(q[2], bk).split())
                if a and b and len(a & b) / len(a | b) >= 0.5:
                    key = "pair:" + "+".join(sorted([p[0], q[0]]))
                    if key not in seen:
                        pairs.append((key, p, q))
    pairs = pairs[:MAX_ITEMS]
    same = []
    for key, p, q in pairs:
        a = ask(SAME_PROMPT.format(brand=p[1], conc=p[3] or q[3] or "concentration unknown", a=p[2], b=q[2]))
        if a.get("same") is True:
            same.append([p[1], p[2], q[2], p[3] or q[3] or "—", "yes" if a.get("sure") is True else "no", f"{p[0]} / {q[0]}"])
            todo("same perfume?", f"{p[1]}: {p[2]} = {q[2]}", f"{p[3] or q[3] or ''} ids {p[0]} / {q[0]}")
    if not new_names and not pairs:
        return f"names: nothing new ({len(perfumes)} perfumes, all asked before)", []
    path = write_list("names", "Perfume names: promotion words",
                      f"Proposals only: nothing was changed. {len(new_names)} names checked, {len(promo)} with words to remove.\n"
                      "Good ones become words that catalog.name_key ignores (then \"- Summer Deal\" no longer splits a perfume).",
                      ["Brand", "Name now", "Name without them", "Removed", "Catalog id"], promo)
    write_list("names", "Perfume names: probably the same perfume",
               f"{len(pairs)} pairs checked (same house and concentration, names overlapping), {len(same)} judged the same.\n"
               "Good ones become a rule in catalog.py so they merge.",
               ["Brand", "Name A", "Name B", "Conc.", "Sure", "Catalog ids"], same)
    return (f"names: {len(new_names)} names checked, {len(promo)} with promotion words; "
            f"{len(pairs)} pairs checked, {len(same)} the same -> {path}"), ["name:" + p[0] for p in new_names] + [k for k, _, _ in pairs]


# ---------- 4. descriptions for the note pages ----------
PAGE_MIN_CONFIRMED = int(os.environ.get("PAGE_MIN_CONFIRMED", "3"))   # as in pages.py
TEXTS_PER_NIGHT = int(os.environ.get("LLM_TEXTS", "100"))   # every note with a page gets a turn in one night
WIKI = "https://en.wikipedia.org/w/api.php"
# Notes whose Wikipedia article has another title than the note's name (the plant or material itself).
WIKI_TITLES = {"sage": "Salvia officinalis", "cedar": "Cedrus", "juniper": "Juniperus communis", "pink pepper": "Schinus molle",
               "violet leaf": "Viola odorata", "violet": "Viola odorata", "lavender": "Lavandula angustifolia",
               "cardamom": "Cardamom", "chestnut": "Castanea sativa", "amber": "Amber (perfumery)", "musk": "Musk",
               "iris": "Orris root", "orris": "Orris root", "oud": "Agarwood", "patchouli": "Patchouli",
               "vetiver": "Chrysopogon zizanioides", "bergamot": "Bergamot orange", "mandarin": "Mandarin orange",
               "orange blossom": "Neroli", "neroli": "Neroli", "tuberose": "Polianthes tuberosa", "jasmine": "Jasmine",
               "rose": "Rose oil", "sandalwood": "Sandalwood", "tonka bean": "Tonka bean", "vanilla": "Vanilla",
               "cinnamon": "Cinnamon", "leather": "Leather", "ambroxan": "Ambroxide", "guaiac wood": "Guaiacum",
               # Perfumery uses another part or plant than the general article: birch = birch tar (smoky, leathery),
               # geranium = Pelargonium (not the Geranium genus), lavandin = the lavender hybrid.
               "birch": "Birch tar", "geranium": "Pelargonium graveolens", "lavandin": "Lavandula × intermedia",
               "rum": "Rum"}
TEXT_PROMPT = """You write short descriptions of perfume notes for a perfume website. Plain, friendly English for
shoppers. No marketing words, no brand or perfume names, no lists.

Note: {note}
Where it sits: {tier}
Notes it is often paired with on our site: {pairs}
Source text (from Wikipedia):
\"\"\"{source}\"\"\"

Reply in JSON: {{"smell": ..., "origin": ..., "from_source": ...}}
- "smell": 2 sentences. First: what it smells like, compared with things people know (fruits, spices, wood,
  sweets, the outdoors), as concrete as you can. {first_rule} Second: what it does in a perfume, and that it is {tier_short}
  (use exactly that; never another tier). Keep to what is common knowledge in perfumery. Avoid empty phrases such
  as "adds depth and longevity", "depth and complexity", "evokes", "invigorating", "a popular choice".
- "origin": 1 sentence on what it is: the plant (or material), the part that is used, and where it is native, as
  far as the source text says. Use ONLY facts in the source. Never claim how much or where most of it comes from:
  no "primarily", "mainly", "mostly", "most", "largest", "main producer", "commonly produced in". If the source
  says nothing useful, write "".
- "from_source": true if every fact in "origin" is in the source text.

An example of the tone we want (cardamom):
{{"smell": "Fresh and spicy at the same time, with hints of eucalyptus, citrus and a little sweetness. It's usually
a top note that gives a perfume a cool, aromatic start.", "origin": "The seeds of plants of the ginger family, from
the genera Elettaria and Amomum, native to the Indian subcontinent and Indonesia.", "from_source": true}}"""

# Words that mark a text as not good enough to go online by itself: claims about quantity or the main producer in
# "origin", and filler in "smell" (both seen in the first night's drafts, 2026-11-26).
CLAIM = re.compile(r"\b(primarily|mainly|mostly|most|largest|main|leading|majority|chiefly|predominantly|commonly "
                   r"produced|best[- ]known)\b", re.I)
FILLER = re.compile(r"depth and (longevity|complexity)|adds? depth|evok|invigorat|popular choice|complexity", re.I)
# Notes perfumers build from other materials: Wikipedia's article is about the real thing (animal hides for
# leather), so a text for these always waits for a person.
ACCORD_NOTES = {"leather", "suede", "amber", "musk", "white musk", "aquatic", "marine", "ozonic", "ambergris", "civet",
                "castoreum", "smoke", "mineral", "salt", "toffee", "caramel", "praline", "cotton candy"}


def wiki_intro(title):
    """(title, url, plain-text intro) of an English Wikipedia article, or None (missing or a disambiguation page)."""
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts|info", "exintro": 1, "explaintext": 1,
                                "redirects": 1, "inprop": "url", "format": "json", "titles": title})
    req = urllib.request.Request(f"{WIKI}?{q}", headers={"User-Agent": "FragranceNotes/1.3 (https://fragrancenotes.app)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pg = next(iter(json.loads(r.read())["query"]["pages"].values()))
    text = (pg.get("extract") or "").strip()
    if "missing" in pg or not text or "may refer to" in text[:300]:
        return None
    return pg["title"], pg.get("fullurl", ""), text[:3000]



def wrong_tier(smell, counts):
    """Why a text's top/heart/base doesn't fit where the note sits in our perfumes, or "" when it fits (or we don't
    know). A tier counts as fitting when at least a third of the perfumes put the note there; the model guessed
    "top note" for birch (smoky birch tar, a base note)."""
    if not counts:
        return ""
    said = {("heart" if t == "middle" else t) for t in re.findall(r"\b(top|heart|middle|base)\b", smell.lower())}
    if not said:
        return ""
    total = sum(counts.values())
    fits = {t for t, c in counts.items() if c / total >= 1 / 3}
    if said & fits:
        return ""
    where = max(counts, key=counts.get)
    return f"says {'/'.join(sorted(said))} note, but in our perfumes it is mostly a {where} note"

def unsupported(origin, source):
    """Names and numbers in the model's origin text that the source doesn't have (a sign it made them up)."""
    words = re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b|\b\d+\b", origin)
    return sorted({w for w in words if w.lower() not in source.lower()})


# Accords and abstract notes have no single material behind them, so Wikipedia's article (about animal hides for
# leather, the sea for aquatic) is the wrong source. For these the model writes only how the note smells, from
# common perfumery knowledge, and "comes from" is this fixed sentence, which is true for all of them.
ACCORD_PROMPT = """You write short descriptions of perfume notes for a perfume website. Plain, friendly English for
shoppers. No marketing words, no brand or perfume names, no lists.

Note: {note} (an accord or a family: perfumers build it from several ingredients, it is not one material)
Where it sits: {tier}
Notes it is often paired with on our site: {pairs}

Reply in JSON: {{"smell": ...}}
- "smell": 2 sentences. First: what it smells like, compared with things people know, as concrete as you can.
  {first_rule} Second: what it does in a perfume, and that it is {tier_short} (use exactly that; never another tier). Avoid
  empty phrases such as "adds depth and longevity", "depth and complexity", "evokes", "invigorating"."""
# The browser extension shows only the first sentence (a short pop-up while shopping), so that sentence has to say
# how the note smells by itself.
FIRST_RULE = ("The first sentence is also shown on its own, so it must say how the note smells by itself: at most 20 "
              "words, starting with the smell itself (\"Warm and sweet, ...\" or \"Cedar smells ...\"), never with "
              "\"It\", and nothing in it about tiers or what the note does in a perfume.")
FIRST_MAX_WORDS = 24


def first_sentence(smell):
    m = re.match(r"(.+?[.!?])(?:\s|$)", (smell or "").strip())
    return m.group(1) if m else (smell or "").strip()


def first_problem(smell):
    """Why the first sentence can't stand alone as the note's smell, or "" (see FIRST_RULE)."""
    f = first_sentence(smell)
    if len(f.split()) > FIRST_MAX_WORDS:
        return f"first sentence too long ({len(f.split())} words)"
    if re.match(r"(it|this|similar to)\b", f, re.I):
        return f"first sentence starts with \"{f.split()[0]}\" instead of the smell"
    if re.search(r"\b(top|heart|middle|base) note|\bperfumes?\b", f, re.I):
        return "first sentence is about the perfume, not the smell"
    return ""


ACCORD_ORIGIN = "In today's perfumes this note isn't taken from one natural material: perfumers build it from several other ingredients."
TRIES_PER_NIGHT = 3        # differently worded attempts per note and night before it waits for the next night
TODO_AFTER = 5             # nights in a row without a passing text before a note shows up in the email

# A second, separate question: the model reads the finished text as a checker and says what is wrong. It caught what
# the word checks can't, like "black pepper can remind of dark chocolate" or birch described as a spring forest
# (in perfumes birch is smoky birch tar). Style is not judged here: "cozy" is fine when the smell is cozy.
FACT_PROMPT = """You check a short description of a perfume note for a perfume website. Look only for facts that
are wrong: a smell the note does not have in perfumes, a comparison that doesn't fit it, the wrong plant, part or
material, a place it is not from, a sentence that says nothing about it at all, or a first sentence that doesn't
say what the note smells like. Do not judge the style or the
choice of words.

Note: {note}
Smells like: "{smell}"
Comes from: "{origin}"

Reply in JSON: {{"smell_ok": true or false, "smell_problem": "what is wrong, or null",
"origin_ok": true or false, "origin_problem": "what is wrong, or null"}}"""


def fact_check(k, smell, origin, accord):
    """(smell problems, []) the checker found. Only the smell is judged: the origin comes from the source and is
    checked against it, and the checker's own memory is less reliable than Wikipedia (it called saffron's Khorasan
    origin wrong). A smell only fails when the checker objects twice, asked in two ways: once it called saffron's
    well-known hay note wrong."""
    problems = []
    for attempt in (0, 1):
        try:
            a = ask(FACT_PROMPT.format(note=k, smell=smell, origin="(not checked here)"), attempt=attempt)
        except Exception:
            return [], []
        if a.get("smell_ok") is not False:
            return [], []
        problems.append(str(a.get("smell_problem") or "wrong")[:150])
    return [f"fact check: {problems[0]}"], []


def tier_words(counts):
    """("mostly a base note in the perfumes on our site", "usually a base note") from where the note sits in our
    perfumes; two tiers when both hold at least a third ("a top or heart note")."""
    if not counts:
        return "unknown", "a top, heart or base note"
    total = sum(counts.values())
    order = [t for t in ("top", "heart", "base") if counts.get(t, 0) / total >= 1 / 3] or [max(counts, key=counts.get)]
    t = " or ".join(order)
    return f"mostly a {t} note in the perfumes on our site", f"usually a {t} note"


def text_checks(k, smell, origin, source, a, counts, accord):
    """(problems with smell, problems with origin): a text goes online when smell has none; origin is shown only
    when it has none either (otherwise the page shows the smell alone, and the note is tried again for an origin)."""
    s, o = [], []
    if not smell or len(smell) > 400:
        s.append("empty or too long")
    if (m := FILLER.search(smell)):
        s.append(f"empty phrase: \"{m.group(0)}\"")
    if smell and (why := first_problem(smell)):
        s.append(why)
    if not re.search(r"\b(top|heart|middle|base)\b", smell, re.I):
        s.append("doesn't say top, heart or base")
    elif (why := wrong_tier(smell, counts)):
        s.append(why)
    if not accord:
        if not source:
            o.append("no source found")
        if a.get("from_source") is not True:
            o.append("model: origin not fully from the source")
        if (extra := unsupported(origin, source or "")):
            o.append("not in source: " + ", ".join(extra))
        if not origin or len(origin) > 700:
            o.append("empty or too long")
        if (m := CLAIM.search(origin)):
            o.append(f"claim about quantity: \"{m.group(0)}\"")
    return s, o


def job_texts(con, seen):
    """Every note with a page gets a text by itself: tried every night until one passes the checks (new notes
    included), with the tier taken from our own data. Never waits for a person; only a note that failed TODO_AFTER
    nights in a row is mentioned in the email."""
    import accords
    try:
        with open(os.path.join(BASE, "note_texts.json"), encoding="utf-8") as f:
            done = set(json.load(f))
    except FileNotFoundError:
        done = set()
    AUTO.execute("CREATE TABLE IF NOT EXISTS text_tries (key TEXT PRIMARY KEY, nights INTEGER NOT NULL, last TEXT NOT NULL)")
    want, tiers, pairs = {}, {}, {}
    for (data,) in con.execute("SELECT data FROM catalog WHERE confirmed >= ?", (PAGE_MIN_CONFIRMED,)):
        notes = json.loads(data)["notes"]
        here = [n["en"] for ns in notes.values() for n in ns if n.get("en") and n["confirmed"]]
        for tier, ns in notes.items():
            for n in ns:
                if n.get("en") and n["confirmed"]:
                    want[n["en"]] = want.get(n["en"], 0) + 1
                    tiers.setdefault(n["en"], {}).setdefault(tier, 0)
                    tiers[n["en"]][tier] += 1
                    for other in here:
                        if other != n["en"]:
                            pairs.setdefault(n["en"], {}).setdefault(other, 0)
                            pairs[n["en"]][other] += 1
    # Texts already online that say another tier than where the note sits in our perfumes: taken back (every night,
    # also when the data changes), and written again below.
    online = {k: o for k, s, o in AUTO.execute("SELECT key, smell, origin FROM note_text").fetchall()}
    for k, smell in AUTO.execute("SELECT key, smell FROM note_text").fetchall():
        why = wrong_tier(smell, tiers.get(k))
        if why:
            AUTO.execute("DELETE FROM note_text WHERE key=?", (k,))
            changed("note text taken back", k, why + " (written again)")
            online.pop(k)
    AUTO.commit()
    # Texts online whose first sentence can't stand alone (the extension shows only that): written again, and the
    # old text stays online until a new one passes every check.
    redo = {k for k, smell in AUTO.execute("SELECT key, smell FROM note_text").fetchall() if first_problem(smell)}
    accord_keys = ACCORD_NOTES | set(accords.FAMILIES)
    # Without a text, or online with the smell only (no origin yet, and one could exist).
    new = [k for k in want if k not in done and (k not in online or k in redo or (not online[k] and k not in accord_keys))]
    new = sorted(new, key=lambda k: (k in online, -want[k], k))[:TEXTS_PER_NIGHT]
    if not new:
        return f"texts: nothing new ({len(want)} notes with a page, {len(done & set(want)) + len(online)} have a text)", []
    rows, drafts, wrote = [], {}, 0
    for k in new:
        accord = k in accord_keys
        source, url = "", ""
        if not accord:
            try:
                src = wiki_intro(WIKI_TITLES.get(k, k[:1].upper() + k[1:]))
            except Exception as err:   # Wikipedia not reachable: this note again next night, the others go on
                print(f"llm review texts: {k} skipped ({err})", flush=True)
                continue
            if src:
                _, url, source = src
        tier, tier_short = tier_words(tiers.get(k))
        with_ = ", ".join(sorted(pairs.get(k, {}), key=lambda x: -pairs[k][x])[:6]) or "none yet"
        prompt = (ACCORD_PROMPT if accord else TEXT_PROMPT).format(
            note=k, tier=tier, tier_short=tier_short, pairs=with_, first_rule=FIRST_RULE, source=source or "(none found: leave origin empty)")
        best, feedback = None, ""
        for attempt in range(TRIES_PER_NIGHT):
            try:
                a = ask(prompt + feedback, attempt=attempt)
            except Exception as err:   # the model server failed once (HTTP 500): next attempt, or next night
                print(f"llm review texts: {k} attempt {attempt} failed ({err})", flush=True)
                continue
            smell = str(a.get("smell") or "").strip()
            origin = ACCORD_ORIGIN if accord else str(a.get("origin") or "").strip()
            s, o = text_checks(k, smell, origin, source, a, tiers.get(k), accord)
            if not s:   # only a text that passed the simple checks is worth the extra question
                fs, fo = fact_check(k, smell, origin if not o else "", accord)
                s, o = s + fs, o + fo
            # The next attempt hears what was wrong with this one.
            feedback = ("\n\nA checker found problems in an earlier answer: " + "; ".join(s + o)[:400]
                        + ". Write it again without those mistakes.") if s or o else ""
            score = (not s, not o)
            if best is None or score > best[0]:
                best = (score, smell, origin, s, o)
            if not s and not o:
                break
        if best is None:
            continue
        _, smell, origin, s, o = best
        drafts[k] = {"smell": smell, "origin": origin, "source": url, "problems": s + o}
        if not s:
            if o and k in online and k not in redo:   # it had the smell already and still no good origin: nothing new
                pass
            elif o and k in redo:   # a better smell; the origin that was online stays
                AUTO.execute("UPDATE note_text SET smell=?, night=? WHERE key=?", (smell, DAY, k))
                changed("note text", k, smell[:100] + " (smell rewritten: first sentence)")
                wrote += 1
            else:
                AUTO.execute("INSERT OR REPLACE INTO note_text (key, smell, origin, source, night) VALUES (?,?,?,?,?)",
                             (k, smell, "" if o else origin, url if not o else "", DAY))
                changed("note text", k, smell[:100] + (" (without origin: " + "; ".join(o) + ")" if o else ""))
                wrote += 1
        if s or (o and not accord):
            n = AUTO.execute("SELECT nights FROM text_tries WHERE key=?", (k,)).fetchone()
            n = (n[0] if n else 0) + 1
            AUTO.execute("INSERT OR REPLACE INTO text_tries (key, nights, last) VALUES (?,?,?)", (k, n, DAY))
            if s and n >= TODO_AFTER:
                todo("note text", k, f"no good text after {n} nights: " + "; ".join(s))
        else:
            AUTO.execute("DELETE FROM text_tries WHERE key=?", (k,))
        AUTO.commit()   # saved per note: a long night that stops halfway keeps what it wrote
        rows.append([k, smell, origin, "; ".join(s + o) or "ok", url])
    path = write_list("texts", "Note descriptions written tonight",
                      "Online by themselves when the smell text passed every check; the origin only when it passed too.",
                      ["Note", "Smells like", "Comes from", "Problems", "Source"], rows)
    with open(os.path.join(OUT, f"texts-{DAY}.json"), "w", encoding="utf-8") as f:
        json.dump(drafts, f, ensure_ascii=False, indent=2)
    os.chmod(os.path.join(OUT, f"texts-{DAY}.json"), 0o600)
    return f"texts: {len(rows)} notes tried, {wrote} texts online -> {path}", []


# ---------- 6. bottle photos from Wikimedia Commons ----------
def job_photos(con, seen):
    """No model needed: for published perfumes without a bottle photo, free photos on Wikimedia Commons that match
    the brand and name. Only a list: a person checks it's the right perfume and bottle (not an older version or
    another concentration) and adds the good ones to server/perfume_photos.json."""
    import notephotos
    try:
        with open(os.path.join(BASE, "perfume_photos.json"), encoding="utf-8") as f:
            done = set(json.load(f))
    except FileNotFoundError:
        done = set()
    have = {r[0] for r in con.execute("SELECT gtin FROM page_images WHERE file IS NOT NULL")} if \
        con.execute("SELECT 1 FROM sqlite_master WHERE name='page_images'").fetchone() else set()
    todo = []
    for pid, brand, name, data in con.execute("SELECT id, brand, name, data FROM catalog WHERE confirmed >= ?", (PAGE_MIN_CONFIRMED,)):
        gtins = json.loads(data).get("gtins", [])
        if pid in done or pid in seen or "c-" + pid in have or any(g in have for g in gtins):
            continue
        todo.append((pid, brand, name))
    rows, asked = [], []
    for pid, brand, name in todo[:20]:
        asked.append(pid)
        q = urllib.parse.urlencode({"action": "query", "list": "search", "srnamespace": 6, "srlimit": 8, "format": "json",
                                    "srsearch": f'"{name}" {brand} perfume'})
        req = urllib.request.Request(f"https://commons.wikimedia.org/w/api.php?{q}", headers={"User-Agent": notephotos.USER_AGENT})
        time.sleep(1)   # be gentle with the Commons API
        with urllib.request.urlopen(req, timeout=30) as r:
            answer = json.loads(r.read())
        if "query" not in answer:   # an error or a "slow down" answer: try this perfume again next night
            asked.pop()
            rows.append([f"{brand} {name}", "—", "—", "search failed: " + str(answer.get("error", {}).get("code", "?")), ""])
            continue
        hits = [h["title"].removeprefix("File:") for h in answer["query"]["search"]]
        hits = [h for h in hits if re.search(r"\.(jpe?g|png|webp|tiff?)$", h, re.I)]
        free = notephotos.commons_info(hits) if hits else {}
        if not free:
            rows.append([f"{brand} {name}", "—", "—", "no free photo found", ""])
        for file, info in list(free.items())[:3]:
            rows.append([f"{brand} {name}", f"[{file}]({info['page']})", info["license"], info["artist"][:40],
                         f'"{pid}": "{file}"'])
    if not rows:
        return "photos: nothing new", []
    path = write_list("photos", "Bottle photos to review (Wikimedia Commons)",
                      "Free licences only. Open each link and check it is this perfume (same version and bottle).\n"
                      "Good ones: copy the last column into server/perfume_photos.json and deploy.",
                      ["Perfume", "Commons file", "Licence", "Maker", "Line for perfume_photos.json"], rows)
    return f"photos: {len(asked)} perfumes checked -> {path}", asked


# ---------- 5. shops people added themselves ----------
def job_shops(con, seen):
    """No model needed: the domains users added as their own shop (opt-in, see app.add_suggestions), with how
    many installs added each. New ones are listed; popular ones are candidates for the built-in list."""
    try:
        rows = con.execute("SELECT domain, COUNT(*) FROM shop_suggestions GROUP BY domain ORDER BY COUNT(*) DESC, domain").fetchall()
    except sqlite3.OperationalError:   # table not there yet
        return "shops: no table yet", []
    new = [(d, n) for d, n in rows if f"{d}:{n}" not in seen]
    if not new:
        return f"shops: nothing new ({len(rows)} domains)", []
    path = write_list("shops", "Shops people added themselves",
                      "Domains only, from users who share. Popular ones can go into manifest.json (content_scripts\n"
                      "matches) and server/shops.txt; check first that it sells perfume and shows product data.",
                      ["Domain", "Installs"], new)
    return f"shops: {len(new)} new or grown -> {path}", [f"{d}:{n}" for d, n in new]


# ---------- 7. names the gate held (gate.py) ----------
GATE_NAME_PROMPT = """A perfume name taken from a web shop's product title still has leftovers that are not part of
the perfume's own name: a colour or size option, packaging words, brackets, loose dashes, or the brand repeated.
Brand: "{brand}". What our check found: {problems}.
Remove only those leftovers. Never add, translate, respell or reorder words. Keep versions such as "Intense",
"Elixir", "Absolu", "Le Parfum", "Pour Homme", "Night". If nothing should be removed, return the name unchanged.
Reply in JSON: {{"clean": "the name without the leftovers"}}

Name: "{name}\""""


def job_gate(con, seen):
    """Names the gate held: the model may leave words out (never others), and the result must pass the gate's own
    name check. Stored in auto.db name_fix; the gate checks it again before a page uses it."""
    import gate
    try:
        items = con.execute("SELECT id, kind, value FROM gate_review WHERE kind IN ('new', 'name')").fetchall()
    except sqlite3.Error:
        return "gate names: no review list yet", []
    done = dict(AUTO.execute("SELECT id, before FROM name_fix"))
    asked, fixed = [], 0
    for pid, kind, value in items[:MAX_ITEMS]:
        row = con.execute("SELECT brand, name FROM catalog WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        brand, name = row
        problems = gate.name_problems(name, brand)
        if not problems or done.get(pid) == name or f"gate:{pid}:{name}" in seen:
            continue
        asked.append(f"gate:{pid}:{name}")
        a = ask(GATE_NAME_PROMPT.format(brand=brand, problems="; ".join(problems), name=name))
        clean = gate.keep_words(name, str(a.get("clean") or ""))
        removed = set(catalog.plain(name).split()) - set(catalog.plain(clean).split())
        if (not clean or not gate.deletion_only(name, clean) or gate.name_problems(clean, brand)
                or removed & VERSION_WORDS):
            todo("name the gate held", f"{brand} {name}", "; ".join(problems) + (f" (the model suggested “{clean}”, not safe)" if clean else ""))
            continue
        AUTO.execute("INSERT OR REPLACE INTO name_fix (id, name, before, night) VALUES (?,?,?,?)", (pid, clean, name, DAY))
        changed("name cleaned", f"{brand} {name}", f"→ {clean}")
        fixed += 1
    return f"gate names: {len(asked)} held names asked, {fixed} cleaned", asked


def undo(night):
    """Take back what the job fixed itself in one night: `python3 llm_review.py --undo 2026-11-26`. The catalog
    follows at its next hourly rebuild."""
    con = maintenance.open_rw(os.path.join(os.path.dirname(DB), "auto.db"))
    n = con.execute("DELETE FROM note_alias WHERE night=?", (night,)).rowcount
    t = con.execute("DELETE FROM note_text WHERE night=?", (night,)).rowcount
    f = con.execute("DELETE FROM name_fix WHERE night=?", (night,)).rowcount
    con.execute("INSERT INTO changes (night, kind, item, detail) VALUES (?,?,?,?)",
                (DAY, "undo", night, f"{n} note names, {t} note texts and {f} perfume names taken back"))
    con.commit()
    con.close()
    print(f"llm review undo {night}: {n} note names, {t} note texts and {f} perfume names taken back", flush=True)


def main():
    global AUTO
    if not os.path.isfile(DB):
        raise RuntimeError(f"database not found: {DB}")
    auto_path = os.path.join(os.path.dirname(DB), "auto.db")
    AUTO = maintenance.open_rw(auto_path)
    os.chmod(auto_path, 0o644)   # the API (another user in its container) only reads it
    os.makedirs(OUT, mode=0o700, exist_ok=True)
    seen_file = os.path.join(OUT, "seen.json")
    seen = json.load(open(seen_file)) if os.path.exists(seen_file) else {}
    if isinstance(seen, list):   # the first version only had note names
        seen = {"notes": seen}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    failed = []
    try:
        for name, job in (("notes", job_notes), ("obf", job_obf), ("names", job_names), ("texts", job_texts), ("shops", job_shops), ("photos", job_photos), ("gate", job_gate)):
            try:
                line, asked = job(con, set(seen.get(name, [])))
            except Exception as e:   # one job failing doesn't stop the others (what it fixed so far is kept)
                AUTO.commit()
                failed.append(f"{name}: {e}")
                continue
            AUTO.commit()
            seen[name] = sorted(set(seen.get(name, [])) | set(asked))
            with open(seen_file + ".tmp", "w") as f:
                json.dump(seen, f)
            os.replace(seen_file + ".tmp", seen_file)
            print(f"llm review {line}", flush=True)
    finally:
        con.close()
        AUTO.close()
    if failed:
        raise RuntimeError("; ".join(failed))


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--undo" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", sys.argv[2]):
            undo(sys.argv[2])
        else:
            main()
    except Exception as e:
        print(f"llm review FAILED: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
