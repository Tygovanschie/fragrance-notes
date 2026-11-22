"""Fragrance Notes price API: anonymous, crowd-sourced perfume prices.

Python standard library only. Runs behind Tailscale Funnel, which does TLS.

  POST /prices              {perfumeId, ml, price, currency, shop}   header X-Install-Id: <uuid4>
  GET  /prices/{perfumeId}  ?currency=EUR (optional; defaults to the most-reported one)
  GET  /health

Privacy: no IP addresses are stored or logged. The install id is a random UUID made by the
extension; only a salted hash of it is stored. Reports older than RETENTION_DAYS are deleted.
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import statistics
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

DB_PATH = os.environ.get("DB_PATH", "/data/prices.db")
SALT_PATH = os.environ.get("SALT_PATH", os.path.join(os.path.dirname(DB_PATH), "salt"))
SHOPS_FILE = os.environ.get("SHOPS_FILE", os.path.join(os.path.dirname(__file__), "shops.txt"))
PORT = int(os.environ.get("PORT", "8787"))
# Browsers only: CORS is not a security boundary, curl can post anyway (rate limits handle that).
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "chrome-extension://hhhiolpcmkdkegcmjmpglcnfolohldgc").split(",") if o.strip()}

WINDOW_DAYS = 30          # stats cover the last 30 days
RETENTION_DAYS = 90       # rows older than this are deleted
MAX_BODY = 1024
LIMITS = [(600, 60), (86400, 500)]   # per install: 60 reports / 10 min, 500 / day (a page sends up to 8 sizes)
GLOBAL_LIMIT = (3600, 5000)          # all installs together
# Outliers are never rejected or deleted, only left out when stats are calculated (on every GET):
# per size, a shop whose median per-ml price is below OUTLIER_LOW x or above OUTLIER_HIGH x the median
# of all shops' values is dropped, but only once the size has at least OUTLIER_MIN_SHOPS shops.
OUTLIER_LOW = float(os.environ.get("OUTLIER_LOW", "0.4"))
OUTLIER_HIGH = float(os.environ.get("OUTLIER_HIGH", "2.5"))
OUTLIER_MIN_SHOPS = 3
# Neighbouring sizes: every shop's per-ml price for a size is compared with the nearest smaller and the
# nearest larger size of the same perfume that OTHER shops sell (median of those shops' values).
# Bigger bottles are normally a bit cheaper per ml, so a price is left out when it breaks that badly:
#  - a smaller bottle more than 15% cheaper per ml than the larger size  (below SMALLER_MAX x larger)
#  - a larger bottle under 0.4x the per-ml price of the smaller size     (below LARGER_MIN x smaller)
SMALLER_MAX = float(os.environ.get("SMALLER_MAX", "0.85"))
LARGER_MIN = float(os.environ.get("LARGER_MIN", "0.4"))
# A size's "shops" (what the extension's deal label uses) stays empty until this many distinct
# installs reported the kept prices. Raise it later without an extension update.
LABEL_MIN_INSTALLS = int(os.environ.get("LABEL_MIN_INSTALLS", "1"))

# Rough EUR value of one unit, only for the absolute sanity bounds below (not for display).
EUR_PER = {"EUR": 1, "USD": 0.9, "GBP": 1.15, "CHF": 1.05, "PLN": 0.23, "SEK": 0.087, "DKK": 0.134,
           "NOK": 0.085, "CZK": 0.04, "RON": 0.2, "HUF": 0.0025, "TRY": 0.025, "RUB": 0.01, "UAH": 0.022,
           "AUD": 0.6, "CAD": 0.66, "JPY": 0.006, "KRW": 0.00065}
PER_ML_EUR = (0.03, 150.0)   # nothing sells below 3 cents or above 150 euro per ml

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
HOST_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def load_shops():
    with open(SHOPS_FILE, encoding="utf-8") as f:
        return {l.strip().lower() for l in f if l.strip() and not l.startswith("#")}


SHOPS = load_shops()


def load_salt():
    try:
        with open(SALT_PATH, "rb") as f:
            return f.read()
    except FileNotFoundError:
        salt = secrets.token_bytes(32)
        with open(SALT_PATH, "wb") as f:
            f.write(salt)
        return salt


SALT = b""


def db():
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS reports (
            perfume_id INTEGER NOT NULL, ml REAL NOT NULL, price REAL NOT NULL, currency TEXT NOT NULL,
            per_ml REAL NOT NULL, shop TEXT NOT NULL, install TEXT NOT NULL, t INTEGER NOT NULL,
            UNIQUE (install, perfume_id, shop, ml))""")
        con.execute("CREATE INDEX IF NOT EXISTS reports_lookup ON reports (perfume_id, currency, t)")
        # Price history for "lowest in 30 days": one row per install, perfume, shop, size, currency and
        # UTC day, holding the lowest price of that day. `reports` keeps only each install's latest price.
        new = not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_lows'").fetchone()
        con.execute("""CREATE TABLE IF NOT EXISTS daily_lows (
            install TEXT NOT NULL, perfume_id INTEGER NOT NULL, shop TEXT NOT NULL, ml REAL NOT NULL,
            currency TEXT NOT NULL, day TEXT NOT NULL, price REAL NOT NULL, t INTEGER NOT NULL,
            PRIMARY KEY (install, perfume_id, shop, ml, currency, day))""")
        con.execute("CREATE INDEX IF NOT EXISTS daily_lows_lookup ON daily_lows (perfume_id, currency, day)")
        if new:   # one-time migration: start the history with the prices we have
            con.execute("""INSERT OR IGNORE INTO daily_lows (install, perfume_id, shop, ml, currency, day, price, t)
                SELECT install, perfume_id, shop, ml, currency, date(t / 1000, 'unixepoch'), price, t FROM reports""")


def purge_old():
    cutoff = now_ms() - RETENTION_DAYS * 86400_000
    with db() as con:
        con.execute("DELETE FROM reports WHERE t < ?", (cutoff,))
        con.execute("DELETE FROM daily_lows WHERE day < ?", (day_of(cutoff),))


def day_of(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def now_ms():
    return int(time.time() * 1000)


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.hits = defaultdict(deque)

    def allow(self, key, limits):
        """Sliding windows; returns seconds to wait (0 = allowed, and the hit is counted)."""
        t = time.monotonic()
        with self.lock:
            q = self.hits[key]
            longest = max(w for w, _ in limits)
            while q and q[0] <= t - longest:
                q.popleft()
            for window, n in limits:
                recent = [x for x in q if x > t - window]
                if len(recent) >= n:
                    return int(recent[0] + window - t) + 1
            q.append(t)
            if len(self.hits) > 100_000:   # forget idle installs
                for k in [k for k, v in self.hits.items() if not v or v[-1] < t - longest]:
                    del self.hits[k]
            return 0


LIMITER = RateLimiter()


class Invalid(Exception):
    pass


def num(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not (lo <= v <= hi):
        raise Invalid(f"{name} must be a number between {lo} and {hi}")
    return float(v)


def shop_of(v):
    if not isinstance(v, str):
        raise Invalid("shop must be a string")
    s = v.strip().lower()
    if s.startswith("www."):
        s = s[4:]
    if len(s) > 100 or not HOST_RE.match(s):
        raise Invalid("shop must be a host name like douglas.nl")
    # Store the shop as its built-in domain (nl.example.com -> example.com).
    for d in (s, *[s.split(".", i)[-1] for i in range(1, s.count("."))]):
        if d in SHOPS:
            return d
    raise Invalid("shop is not one of the supported shops")


def validate(body):
    if not isinstance(body, dict):
        raise Invalid("body must be a JSON object")
    extra = set(body) - {"perfumeId", "ml", "price", "currency", "shop"}
    if extra:
        raise Invalid("unknown fields: " + ", ".join(sorted(extra)))
    pid = body.get("perfumeId")
    if isinstance(pid, int) and not isinstance(pid, bool):
        pid = str(pid)
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise Invalid("perfumeId must be a Fragrantica perfume number")
    ml = num(body.get("ml"), "ml", 0.5, 1000)
    price = num(body.get("price"), "price", 0.01, 10_000_000)
    cur = body.get("currency")
    if cur not in EUR_PER:
        raise Invalid("currency must be one of " + ", ".join(sorted(EUR_PER)))
    per_eur = price / ml * EUR_PER[cur]
    if not (PER_ML_EUR[0] <= per_eur <= PER_ML_EUR[1]):
        raise Invalid("price per ml is not plausible")
    return int(pid), round(ml, 2), round(price, 2), cur, shop_of(body.get("shop"))


def stats(pid, currency=None):
    since = now_ms() - WINDOW_DAYS * 86400_000
    with db() as con:
        curs = [r[0] for r in con.execute(
            "SELECT currency FROM reports WHERE perfume_id=? AND t>=? GROUP BY currency ORDER BY COUNT(*) DESC",
            (pid, since))]
        cur = currency if currency in curs else (curs[0] if curs and not currency else currency)
        all_rows = con.execute(
            "SELECT ml, price, per_ml, shop, install, t FROM reports WHERE perfume_id=? AND currency=? AND t>=?",
            (pid, cur, since)).fetchall() if cur else []
        history = defaultdict(list)   # (ml, shop) -> daily lowest prices in the window
        for ml, shop, price in (con.execute(
                "SELECT ml, shop, price FROM daily_lows WHERE perfume_id=? AND currency=? AND day>=?",
                (pid, cur, day_of(since))) if cur else []):
            history[(ml, shop)].append(price)
    out = {"perfumeId": str(pid), "currency": cur, "currencies": curs, "days": WINDOW_DAYS, "count": len(all_rows)}
    if not all_rows:
        return out
    r4 = lambda x: round(x, 4)

    # Per size: one value per shop (that shop's median), then drop outlier shops against their median.
    by_size = defaultdict(lambda: defaultdict(list))   # ml -> shop -> rows
    for r in all_rows:
        by_size[r["ml"]][r["shop"]].append(r)
    # Pass 1: sizes with 3+ shops, against the median of their own shops.
    values, kept_by = {}, {}
    for ml, shops in by_size.items():
        value = {s: statistics.median(r["per_ml"] for r in rs) for s, rs in shops.items()}
        kept = dict(value)
        if len(value) >= OUTLIER_MIN_SHOPS:
            base = statistics.median(value.values())
            kept = {s: v for s, v in value.items() if OUTLIER_LOW * base <= v <= OUTLIER_HIGH * base}
        values[ml], kept_by[ml] = value, kept
    # Pass 2: neighbouring sizes, using only other shops' prices (as kept by pass 1) as reference.
    def neighbour(ml, shop, sizes_in_order):
        """Median of other shops' values at the nearest size in that order that has any."""
        for m in sizes_in_order:
            other = [v for s, v in pass1[m].items() if s != shop]
            if other:
                return statistics.median(other)
        return None
    order = sorted(by_size)
    pass1 = {ml: dict(k) for ml, k in kept_by.items()}   # judge against pass-1 values, not each other's results
    for i, ml in enumerate(order):
        keep = {}
        for shop, v in pass1[ml].items():
            larger = neighbour(ml, shop, order[i + 1:])
            smaller = neighbour(ml, shop, reversed(order[:i]))
            if (larger is not None and v < SMALLER_MAX * larger) or (smaller is not None and v < LARGER_MIN * smaller):
                continue
            keep[shop] = v
        kept_by[ml] = keep

    sizes, dropped = [], set()   # dropped: (ml, shop) pairs left out everywhere
    for ml, shops in sorted(by_size.items()):
        value, kept = values[ml], kept_by[ml]
        dropped.update((ml, s) for s in value if s not in kept)
        kept_rows = [r for s in kept for r in shops[s]]
        installs = len({r["install"] for r in kept_rows})
        show = installs >= LABEL_MIN_INSTALLS
        sizes.append({
            "ml": ml, "count": len(kept_rows),
            "median": r4(statistics.median(r["per_ml"] for r in kept_rows)) if kept_rows else None,
            # The extension compares a page with the *other* shops in here (one value per shop, so one
            # busy shop doesn't outweigh the rest). Empty until enough distinct installs back it up.
            "shops": {s: r4(v) for s, v in sorted(kept.items())} if show else {},
            # Lowest full price (not per ml) each kept shop had for this size in the last 30 days, from the
            # daily history; same visibility rule as "shops".
            "lows": lows_for(ml, kept, shops, kept_rows, history) if show else {},
            "installs": installs, "outliers": len(value) - len(kept),
        })

    rows = [r for r in all_rows if (r["ml"], r["shop"]) not in dropped]
    per = [r["per_ml"] for r in rows]
    if not per:   # everything was left out
        out.update({"count": 0, "shopCount": 0, "sizes": sizes, "cheapest": []})
        return out
    best = {}
    for r in rows:
        b = best.get(r["shop"])
        if b is None or r["per_ml"] < b["per_ml"] or (r["per_ml"] == b["per_ml"] and r["t"] > b["t"]):
            best[r["shop"]] = r
    out.update({
        "count": len(rows),
        "median": r4(statistics.median(per)), "min": r4(min(per)), "max": r4(max(per)),
        "shopCount": len(best),
        "sizes": sizes,
        "cheapest": [{"shop": r["shop"], "perMl": r4(r["per_ml"]), "ml": r["ml"], "price": r["price"], "t": r["t"]}
                     for r in sorted(best.values(), key=lambda r: r["per_ml"])[:5]],
    })
    return out


def lows_for(ml, kept, shops, kept_rows, history):
    """Per kept shop: the lowest daily price in the window. A past day only counts if its per-ml price is
    at least OUTLIER_LOW x the size's current median, so an old misreading (later corrected, so no longer
    in `reports`) can't stay on show as "lowest in 30 days" for a month."""
    floor = OUTLIER_LOW * statistics.median(r["per_ml"] for r in kept_rows) * ml
    out = {}
    for s in sorted(kept):
        current = min(r["price"] for r in shops[s])          # always valid: it passed the filters
        past = [p for p in history.get((ml, s), []) if p >= floor]
        out[s] = round(min([current] + past), 2)
    return out


def add_report(install, pid, ml, price, cur, shop):
    # No outlier check here: odd prices are stored and only left out in stats() (see OUTLIER_LOW).
    per, t = price / ml, now_ms()
    with db() as con:
        con.execute("""INSERT INTO reports (perfume_id, ml, price, currency, per_ml, shop, install, t)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT (install, perfume_id, shop, ml) DO UPDATE SET
              price=excluded.price, currency=excluded.currency, per_ml=excluded.per_ml, t=excluded.t""",
                    (pid, ml, price, cur, per, shop, install, t))
        # SET expressions see the old row, so both use the stored price for the comparison.
        con.execute("""INSERT INTO daily_lows (install, perfume_id, shop, ml, currency, day, price, t)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT (install, perfume_id, shop, ml, currency, day) DO UPDATE SET
              t = CASE WHEN excluded.price < price THEN excluded.t ELSE t END,
              price = MIN(price, excluded.price)""",
                    (install, pid, shop, ml, cur, day_of(t), price, t))


class Handler(BaseHTTPRequestHandler):
    server_version = "fragrance-api"
    sys_version = ""
    timeout = 10                 # drop slow clients
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # no client addresses in the logs
        pass

    def log_request(self, code="-", size="-"):
        print(f"{self.command} {urlsplit(self.path).path} {code}", flush=True)

    def cors(self):
        origin = self.headers.get("Origin")
        if self.command == "GET":
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def reply(self, code, obj, headers=()):
        data = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers:
            self.send_header(k, v)
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Install-Id")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/health":
            return self.reply(200, {"ok": True})
        m = re.fullmatch(r"/prices/([0-9]+)", u.path)
        if not m or not ID_RE.match(m.group(1)):
            return self.reply(404, {"error": "not found"})
        cur = (parse_qs(u.query).get("currency") or [None])[0]
        if cur is not None and cur not in EUR_PER:
            return self.reply(400, {"error": "unknown currency"})
        self.reply(200, stats(int(m.group(1)), cur), [("Cache-Control", "public, max-age=300")])

    def do_POST(self):
        self.close_connection = True   # never reuse a connection whose body we may not have read
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        # Read (or drain) the body first, so an early error reply isn't lost to a connection reset.
        raw = self.rfile.read(min(max(length, 0), 65536))
        if not (0 < length <= MAX_BODY):
            return self.reply(413 if length > MAX_BODY else 400, {"error": "body must be 1-1024 bytes"})
        if urlsplit(self.path).path != "/prices":
            return self.reply(404, {"error": "not found"})
        if self.headers.get("Origin") and self.headers.get("Origin") not in ALLOWED_ORIGINS:
            return self.reply(403, {"error": "origin not allowed"})
        install = (self.headers.get("X-Install-Id") or "").lower()
        if not UUID_RE.match(install):
            return self.reply(400, {"error": "X-Install-Id must be a random UUID"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.reply(415, {"error": "use application/json"})
        key = hashlib.sha256(SALT + install.encode()).hexdigest()[:32]
        for k, lim in ((key, LIMITS), ("*", [GLOBAL_LIMIT])):
            wait = LIMITER.allow(k, lim)
            if wait:
                return self.reply(429, {"error": "too many reports"}, [("Retry-After", str(wait))])
        try:
            add_report(key, *validate(json.loads(raw)))
        except Invalid as e:
            return self.reply(422, {"error": str(e)})
        except ValueError:   # includes JSON and UTF-8 decode errors
            return self.reply(400, {"error": "invalid JSON"})
        self.reply(201, {"ok": True})


def purge_loop():
    while True:
        time.sleep(3600)
        try:
            purge_old()
        except Exception as e:  # keep serving even if a purge fails
            print("purge failed:", e, flush=True)


def make_server(port=PORT):
    global SALT
    SALT = load_salt()
    init_db()
    purge_old()
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    srv = make_server()
    srv.daemon_threads = True
    threading.Thread(target=purge_loop, daemon=True).start()
    print(f"fragrance-api listening on :{PORT}, {len(SHOPS)} shops", flush=True)
    srv.serve_forever()
