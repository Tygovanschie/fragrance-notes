"""What the nightly maintenance job (llm_review.py, on the host) fixed by itself, kept apart from the main database.

The job writes data/auto.db; the API only reads it:
- note_alias: a shop's spelling of a note that the dictionary (catalog.NOTE_WORDS) didn't know, mapped to a note it
  does know ("kardemon" -> cardamom). Only ever to an existing note; catalog.note_key uses them.
- note_text:  a description for a note page, written from the Wikipedia intro and checked against it; note_texts.json
  (reviewed by hand) wins over it.
- changes:    a log of every change, per night (llm_review.py --undo NIGHT takes a night back).
- todo:       what the job didn't dare to fix itself (possible duplicates, possible non-perfumes), for the weekly email.
Nothing here is personal: note names, perfume names and counts.
"""
import datetime
import os
import sqlite3

AUTO_DB = os.environ.get("AUTO_DB", os.path.join(os.path.dirname(os.environ.get("DB_PATH", "/data/prices.db")), "auto.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS note_alias (word TEXT PRIMARY KEY, canon TEXT NOT NULL, night TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS note_text (key TEXT PRIMARY KEY, smell TEXT NOT NULL, origin TEXT NOT NULL,
    source TEXT NOT NULL, night TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS changes (night TEXT NOT NULL, kind TEXT NOT NULL, item TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS todo (night TEXT NOT NULL, kind TEXT NOT NULL, item TEXT NOT NULL, detail TEXT NOT NULL,
    PRIMARY KEY (kind, item));
"""


def open_rw(path=None):
    """The job's own connection (on the host)."""
    con = sqlite3.connect(path or AUTO_DB)
    con.executescript(SCHEMA)
    return con


def _ro(path=None):
    path = path or AUTO_DB
    if not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def aliases(path=None):
    """{shop spelling key: known note} learned by the job; {} when there's nothing (yet)."""
    con = _ro(path)
    if not con:
        return {}
    try:
        return dict(con.execute("SELECT word, canon FROM note_alias"))
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def texts(path=None):
    """{note: {smell, origin, source, sourceName, license}} written by the job."""
    con = _ro(path)
    if not con:
        return {}
    try:
        return {k: {"smell": s, "origin": o, "source": src, "sourceName": "Wikipedia", "license": "CC BY-SA 4.0", "auto": True}
                for k, s, o, src in con.execute("SELECT key, smell, origin, source FROM note_text")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def week(path=None, today=None):
    """What the job did in the last 7 nights and what it left for a person: for GET /maintenance/week (the
    Worker's weekly email)."""
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=7)).isoformat()
    out = {"since": since, "changes": [], "todo": []}
    con = _ro(path)
    if not con:
        return out
    try:
        out["changes"] = [dict(zip(("night", "kind", "item", "detail"), r)) for r in con.execute(
            "SELECT night, kind, item, detail FROM changes WHERE night >= ? ORDER BY night, kind, item", (since,))]
        out["todo"] = [dict(zip(("night", "kind", "item", "detail"), r)) for r in con.execute(
            "SELECT night, kind, item, detail FROM todo WHERE night >= ? ORDER BY kind, night, item LIMIT 60", (since,))]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out
