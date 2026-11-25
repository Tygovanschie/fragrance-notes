"""Votes on the perfume pages: overall rating (stars), longevity, sillage, price value and gender.

No accounts. Voting sets a random code in a cookie (fn_voter, see app.vote_post); only a salted hash of it is
stored, so one browser has one vote per perfume and can change it. A vote needs the "I own it / have worn it"
box ticked. Nothing about the visitor is kept: no IP address (it's only used in memory for rate limits), no
page history. After VOTE_KEEP_DAYS the voter hash is replaced by a random value, like the facts' install hash.

Results are shown from the first vote, with how many votes they are based on; the star rating goes into the
page data for search engines (aggregateRating) only from GOOGLE_MIN voters.
"""
import hashlib
import time

MIN_VOTERS = 1    # results are shown from this many voters
GOOGLE_MIN = 3    # the star rating in the schema.org data from this many
VOTE_KEEP_DAYS = 365

# field: number of steps on its scale (1 … n). Labels are in pages.T (en/nl).
SCALES = {"rating": 5, "longevity": 5, "sillage": 5, "value": 5, "gender": 5}   # sillage had 4 steps until 2026-11-25


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS votes (
        perfume TEXT NOT NULL, voter TEXT NOT NULL, rating INTEGER, longevity INTEGER, sillage INTEGER,
        value INTEGER, gender INTEGER, day TEXT NOT NULL, PRIMARY KEY (perfume, voter))""")
    con.execute("CREATE INDEX IF NOT EXISTS votes_perfume ON votes (perfume)")


class Invalid(ValueError):
    pass


def parse(form):
    """{field: int} from the submitted form ({name: [values]} as parse_qs gives it). Needs the owns box and at
    least one answer; every answer must be on its scale."""
    if (form.get("owns") or [""])[0] != "1":
        raise Invalid("owns")
    out = {}
    for f, n in SCALES.items():
        v = (form.get(f) or [""])[0]
        if v == "":
            continue
        if not v.isdigit() or not 1 <= int(v) <= n:
            raise Invalid(f)
        out[f] = int(v)
    if not out:
        raise Invalid("empty")
    return out


def add(con, perfume, voter, answers, day=None):
    """Store or replace this voter's vote on this perfume. Questions left open keep the earlier answer."""
    day = day or time.strftime("%Y-%m-%d", time.gmtime())
    cols = list(SCALES)
    con.execute(
        f"""INSERT INTO votes (perfume, voter, {', '.join(cols)}, day) VALUES (?, ?, {', '.join('?' * len(cols))}, ?)
            ON CONFLICT (perfume, voter) DO UPDATE SET {', '.join(f'{c}=COALESCE(excluded.{c}, {c})' for c in cols)},
            day=excluded.day""",
        (perfume, voter, *[answers.get(c) for c in cols], day))


def summary(con, perfume):
    """{"voters": n, field: {"n": answers, "avg": mean, "dist": [count per step]}} for one perfume."""
    rows = con.execute(f"SELECT {', '.join(SCALES)} FROM votes WHERE perfume=?", (perfume,)).fetchall()
    out = {"voters": len(rows)}
    for i, (f, n) in enumerate(SCALES.items()):
        vals = [r[i] for r in rows if r[i]]
        dist = [vals.count(s) for s in range(1, n + 1)]
        out[f] = {"n": len(vals), "avg": round(sum(vals) / len(vals), 2) if vals else None, "dist": dist}
    return out


def purge(con, now=None):
    cutoff = time.strftime("%Y-%m-%d", time.gmtime((now or time.time()) - VOTE_KEEP_DAYS * 86400))
    con.execute("""UPDATE votes SET voter = 'old-' || lower(hex(randomblob(12)))
        WHERE day < ? AND voter NOT LIKE 'old-%'""", (cutoff,))


def mine(con, perfume, voter):
    """This voter's answers on this perfume ({field: value}, open questions left out), or None."""
    if not voter:
        return None
    r = con.execute(f"SELECT {', '.join(SCALES)} FROM votes WHERE perfume=? AND voter=?", (perfume, voter)).fetchone()
    return {f: v for f, v in zip(SCALES, r) if v} if r else None


def voter_hash(salt, token):
    return hashlib.sha256(salt + b"vote:" + token.encode()).hexdigest()[:32]
