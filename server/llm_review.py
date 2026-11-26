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
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")
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



def ask(prompt):
    body = json.dumps({"model": MODEL, "prompt": prompt, "format": "json", "stream": False,
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
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
            todo("unknown note", n["name"], f"maybe {str(a.get('english')).strip().lower()[:40]}; seen on {'; '.join(n['perfumes'])}")
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
TEXTS_PER_NIGHT = int(os.environ.get("LLM_TEXTS", "10"))
WIKI = "https://en.wikipedia.org/w/api.php"
# Notes whose Wikipedia article has another title than the note's name (the plant or material itself).
WIKI_TITLES = {"sage": "Salvia officinalis", "cedar": "Cedrus", "juniper": "Juniperus communis", "pink pepper": "Schinus molle",
               "violet leaf": "Viola odorata", "violet": "Viola odorata", "lavender": "Lavandula angustifolia",
               "cardamom": "Cardamom", "chestnut": "Castanea sativa", "amber": "Amber (perfumery)", "musk": "Musk",
               "iris": "Orris root", "orris": "Orris root", "oud": "Agarwood", "patchouli": "Patchouli",
               "vetiver": "Chrysopogon zizanioides", "bergamot": "Bergamot orange", "mandarin": "Mandarin orange",
               "orange blossom": "Neroli", "neroli": "Neroli", "tuberose": "Polianthes tuberosa", "jasmine": "Jasmine",
               "rose": "Rose oil", "sandalwood": "Sandalwood", "tonka bean": "Tonka bean", "vanilla": "Vanilla",
               "cinnamon": "Cinnamon", "leather": "Leather", "ambroxan": "Ambroxide", "guaiac wood": "Guaiacum"}
TEXT_PROMPT = """You write short descriptions of perfume notes for a perfume website. Plain, friendly English for
shoppers. No marketing words, no brand or perfume names, no lists.

Note: {note}
Source text (from Wikipedia):
\"\"\"{source}\"\"\"

Reply in JSON: {{"smell": ..., "origin": ..., "from_source": ...}}
- "smell": 2 sentences. First: what it smells like, compared with things people know (fruits, spices, wood,
  sweets, the outdoors), as concrete as you can. Second: what it does in a perfume and whether it is usually a
  top, heart or base note. Keep to what is common knowledge in perfumery. Avoid empty phrases such as "adds depth
  and longevity", "depth and complexity", "evokes", "invigorating", "a popular choice".
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


def unsupported(origin, source):
    """Names and numbers in the model's origin text that the source doesn't have (a sign it made them up)."""
    words = re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b|\b\d+\b", origin)
    return sorted({w for w in words if w.lower() not in source.lower()})


def job_texts(con, seen):
    try:
        with open(os.path.join(BASE, "note_texts.json"), encoding="utf-8") as f:
            done = set(json.load(f))
    except FileNotFoundError:
        done = set()
    want = {}
    for (data,) in con.execute("SELECT data FROM catalog WHERE confirmed >= ?", (PAGE_MIN_CONFIRMED,)):
        for tier in json.loads(data)["notes"].values():
            for n in tier:
                if n.get("en") and n["confirmed"]:
                    want[n["en"]] = want.get(n["en"], 0) + 1
    new = sorted((k for k in want if k not in done and k not in seen), key=lambda k: (-want[k], k))[:TEXTS_PER_NIGHT]
    if not new:
        return f"texts: nothing new ({len(want)} notes with a page, {len(done & set(want))} have a text)", []
    rows, drafts, asked = [], {}, []
    for k in new:
        src = wiki_intro(WIKI_TITLES.get(k, k[:1].upper() + k[1:]))
        asked.append(k)
        if not src:
            rows.append([k, "—", "—", "no source found: no text (the page shows facts only)", ""])
            continue
        title, url, text = src
        a = ask(TEXT_PROMPT.format(note=k, source=text))
        # One more try when it only used an empty phrase or a claim: tell the model what to leave out.
        for _ in range(1):
            bad = [m.group(0) for m in (FILLER.search(str(a.get("smell") or "")), CLAIM.search(str(a.get("origin") or ""))) if m]
            if not bad:
                break
            a = ask(TEXT_PROMPT.format(note=k, source=text) + "\n\nYour first answer used " + ", ".join(f'"{b}"' for b in bad)
                    + ". Write it again without those words.")
        smell, origin = str(a.get("smell") or "").strip(), str(a.get("origin") or "").strip()
        checks = []
        if a.get("from_source") is not True:
            checks.append("model: origin not fully from the source")
        if (extra := unsupported(origin, text)):
            checks.append("not in source: " + ", ".join(extra))
        if not smell or not origin or len(smell) > 400 or len(origin) > 700:
            checks.append("empty or too long")
        if (m := CLAIM.search(origin)):
            checks.append(f"claim about quantity: \"{m.group(0)}\"")
        if (m := FILLER.search(smell)):
            checks.append(f"empty phrase: \"{m.group(0)}\"")
        if not re.search(r"\b(top|heart|middle|base)\b", smell, re.I):
            checks.append("doesn't say top, heart or base")
        if k in ACCORD_NOTES:
            checks.append("an accord: the source is about the material, not how perfumers make the note")
        drafts[k] = {"smell": smell, "origin": origin, "source": url, "sourceName": "Wikipedia", "license": "CC BY-SA 4.0"}
        # Online by itself only when every check passes: the model says it only used the source, and it added no
        # names or numbers the source doesn't have. Otherwise it waits for a person.
        if not checks:
            AUTO.execute("INSERT OR REPLACE INTO note_text (key, smell, origin, source, night) VALUES (?,?,?,?,?)",
                         (k, smell, origin, url, DAY))
            changed("note text", k, smell[:100])
        else:
            todo("note text", k, "; ".join(checks))
        rows.append([k, smell, origin, "; ".join(checks) or "ok", f"[{title}]({url})"])
    path = write_list("texts", "Note descriptions to review",
                      "Drafts only: nothing is online. Check each text against the source (the model sometimes gets facts\n"
                      "wrong), fix it if needed, and copy the good ones from texts-" + DAY + ".json into server/note_texts.json.",
                      ["Note", "Smells like (draft)", "Comes from (draft)", "Checks", "Source"], rows)
    with open(os.path.join(OUT, f"texts-{DAY}.json"), "w", encoding="utf-8") as f:
        json.dump(drafts, f, ensure_ascii=False, indent=2)
    os.chmod(os.path.join(OUT, f"texts-{DAY}.json"), 0o600)
    return f"texts: {len(drafts)} drafts, {len(rows) - len(drafts)} without a source -> {path}", asked


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


def undo(night):
    """Take back what the job fixed itself in one night: `python3 llm_review.py --undo 2026-11-26`. The catalog
    follows at its next hourly rebuild."""
    con = maintenance.open_rw(os.path.join(os.path.dirname(DB), "auto.db"))
    n = con.execute("DELETE FROM note_alias WHERE night=?", (night,)).rowcount
    t = con.execute("DELETE FROM note_text WHERE night=?", (night,)).rowcount
    con.execute("INSERT INTO changes (night, kind, item, detail) VALUES (?,?,?,?)",
                (DAY, "undo", night, f"{n} note names and {t} note texts taken back"))
    con.commit()
    con.close()
    print(f"llm review undo {night}: {n} note names and {t} note texts taken back", flush=True)


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
        for name, job in (("notes", job_notes), ("obf", job_obf), ("names", job_names), ("texts", job_texts), ("shops", job_shops), ("photos", job_photos)):
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
