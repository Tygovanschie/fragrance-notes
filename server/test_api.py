"""Self-contained API tests: starts the server on a temporary database and talks to it over HTTP.
Run: python test_api.py   (inside the container: docker compose run --rm --no-deps api python test_api.py)"""
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid

TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(TMP, "test.db")
import app  # noqa: E402

ORIGIN = next(iter(app.ALLOWED_ORIGINS))


def call(method, path, body=None, install=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", **(headers or {})}
    if install:
        h["X-Install-Id"] = install
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers


def report(pid=9828, ml=100, price=300, currency="EUR", shop="douglas.nl", install=None, **kw):
    return call("POST", "/prices", {"perfumeId": pid, "ml": ml, "price": price, "currency": currency, "shop": shop},
                install or str(uuid.uuid4()), **kw)


FACT = {"shop": "douglas.nl", "perfumeId": "64501", "brand": "Armani",
        "name": "Emporio Armani Stronger With You Absolutely", "conc": "parfum", "gender": "m",
        "sizes": [50, 100], "gtins": ["3614273642454"],
        "notes": {"top": ["Rum", "Bergamot"], "heart": ["Ceder", "Davana"], "base": ["Lavendel", "Cederhout"]},
        "families": ["Houtachtig", "Oriëntaal"], "lang": "nl"}


def fact(install=None, **changes):
    body = {**FACT, **changes}
    return call("POST", "/facts", {k: v for k, v in body.items() if v is not ...}, install or str(uuid.uuid4()))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global BASE
        cls.srv = app.make_server(0)
        BASE = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        with app.db() as con:
            con.execute("DELETE FROM reports")
            con.execute("DELETE FROM daily_lows")
            con.execute("DELETE FROM facts")
            con.execute("DELETE FROM catalog")
            con.execute("DELETE FROM catalog_keys")
            con.execute("DELETE FROM catalog_gtins")
        app._facts_stats.update(t=0, data=None)
        app.LIMITER.hits.clear()

    def test_health(self):
        self.assertEqual(call("GET", "/health")[0], 200)

    def test_report_and_stats(self):
        self.assertEqual(report(price=300, shop="douglas.nl")[0], 201)
        self.assertEqual(report(price=250, shop="www.notino.nl")[0], 201)
        self.assertEqual(report(ml=50, price=200, shop="nl.zalando.nl")[0], 201)   # normalised to zalando.nl
        self.assertEqual(report(price=99, currency="GBP", shop="notino.co.uk")[0], 201)
        code, s, h = call("GET", "/prices/9828")
        self.assertEqual(code, 200)
        self.assertEqual(h["Access-Control-Allow-Origin"], "*")
        self.assertEqual((s["currency"], s["count"], s["shopCount"]), ("EUR", 3, 3))
        self.assertEqual((s["min"], s["median"], s["max"]), (2.5, 3.0, 4.0))
        self.assertEqual([c["shop"] for c in s["cheapest"]], ["notino.nl", "douglas.nl", "zalando.nl"])
        self.assertEqual(s["sizes"], [
            {"ml": 50.0, "median": 4.0, "count": 1, "shops": {"zalando.nl": 4.0}, "lows": {"zalando.nl": 200.0},
             "installs": 1, "outliers": 0},
            {"ml": 100.0, "median": 2.75, "count": 2, "shops": {"douglas.nl": 3.0, "notino.nl": 2.5},
             "lows": {"douglas.nl": 300.0, "notino.nl": 250.0}, "installs": 2, "outliers": 0}])
        self.assertEqual(sorted(s["currencies"]), ["EUR", "GBP"])
        self.assertEqual(call("GET", "/prices/9828?currency=GBP")[1]["count"], 1)
        self.assertEqual(call("GET", "/prices/1?currency=EUR")[1]["count"], 0)
        self.assertEqual(call("GET", "/prices/9828?currency=XXX")[0], 400)

    def test_neighbouring_sizes(self):
        P = 7777
        for ml, price, shop in [(50, 60, "douglas.nl"), (50, 55, "notino.nl"), (90, 72, "deloox.nl"), (90, 75, "douglas.nl"),
                                (100, 15, "etos.nl"),     # 0.15/ml, larger bottle at 0.18x the 90 ml (~0.82): left out
                                (30, 18, "etos.nl"),      # 0.60/ml, smaller bottle 48% cheaper than 50 ml (1.15): left out
                                (10, 22, "notino.nl")]:   # 2.20/ml, small bottle 2.6x pricier per ml: normal, kept
            self.assertEqual(report(pid=P, ml=ml, price=price, shop=shop)[0], 201)
        s = call("GET", f"/prices/{P}")[1]
        by = {x["ml"]: x for x in s["sizes"]}
        self.assertEqual((by[100]["shops"], by[100]["outliers"], by[100]["count"], by[100]["median"]), ({}, 1, 0, None))
        self.assertEqual((by[30]["shops"], by[30]["outliers"]), ({}, 1))
        self.assertEqual((by[10]["shops"], by[10]["outliers"]), ({"notino.nl": 2.2}, 0))
        self.assertEqual(len(by[50]["shops"]) + len(by[90]["shops"]), 4)   # the normal sizes are untouched
        self.assertNotIn("etos.nl", [c["shop"] for c in s["cheapest"]])
        self.assertEqual((s["min"], s["count"]), (0.8, 5))
        with app.db() as con:                                               # left out, not deleted
            self.assertEqual(con.execute("SELECT COUNT(*) FROM reports WHERE perfume_id=?", (P,)).fetchone()[0], 7)

    def test_lows_lowest_full_price_per_shop(self):
        P = 5151
        report(pid=P, ml=100, price=310, shop="douglas.nl")       # two installs at douglas: lowest wins
        report(pid=P, ml=100, price=289.99, shop="douglas.nl")
        report(pid=P, ml=100, price=300, shop="notino.nl")
        report(pid=P, ml=100, price=30, shop="flaconi.de")         # 0.30/ml outlier: no low for it
        sz = self.size(pid=P)
        self.assertEqual(sz["lows"], {"douglas.nl": 289.99, "notino.nl": 300.0})  # full price, not per ml
        self.assertEqual(set(sz["lows"]), set(sz["shops"]))
        old = app.LABEL_MIN_INSTALLS
        try:
            app.LABEL_MIN_INSTALLS = 10                             # not enough installs: hidden like shops
            sz = self.size(pid=P)
            self.assertEqual((sz["shops"], sz["lows"]), ({}, {}))
        finally:
            app.LABEL_MIN_INSTALLS = old

    def past(self, days, price, pid=5252, shop="douglas.nl", ml=100.0):
        t = app.now_ms() - days * 86400_000
        with app.db() as con:
            con.execute("INSERT INTO daily_lows VALUES (?,?,?,?,?,?,?,?)",
                        ("someinstall", pid, shop, ml, "EUR", app.day_of(t), price, t))

    def test_lows_keep_the_days_lowest_but_comparison_uses_latest(self):
        P, me = 5252, str(uuid.uuid4())
        for price in (300, 280, 320):                     # one install, same day: price goes down, then up
            report(pid=P, price=price, shop="douglas.nl", install=me)
        report(pid=P, price=300, shop="notino.nl")
        sz = self.size(pid=P)
        self.assertEqual(sz["shops"]["douglas.nl"], 3.2)   # shops/medians: the latest price
        self.assertEqual(sz["lows"]["douglas.nl"], 280.0)  # lows: the day's lowest
        with app.db() as con:
            self.assertEqual(tuple(con.execute("SELECT COUNT(*), MIN(price) FROM daily_lows WHERE shop='douglas.nl'").fetchone()), (1, 280.0))

    def test_lows_cover_30_days_and_skip_old_misreadings(self):
        P = 5252
        report(pid=P, price=300, shop="douglas.nl")
        report(pid=P, price=310, shop="notino.nl")
        self.past(10, 250)                                  # 10 days ago: counts
        self.past(40, 200)                                  # 40 days ago: outside the window
        self.past(5, 30)                                    # 0.30/ml misreading, below 0.4x the median: ignored
        self.assertEqual(self.size(pid=P)["lows"], {"douglas.nl": 250.0, "notino.nl": 310.0})
        self.past(3, 199, shop="flaconi.de")                # history of a shop with no current price: not shown
        self.assertNotIn("flaconi.de", self.size(pid=P)["lows"])

    def test_purge_removes_old_history(self):
        self.past(app.RETENTION_DAYS + 5, 250)
        self.past(10, 260)
        app.purge_old()
        with app.db() as con:
            self.assertEqual([r[0] for r in con.execute("SELECT price FROM daily_lows")], [260.0])

    def test_migration_fills_history_from_reports(self):
        import sqlite3
        path, old = os.path.join(TMP, "migrate.db"), app.DB_PATH
        con = sqlite3.connect(path)
        con.execute("""CREATE TABLE reports (perfume_id INTEGER NOT NULL, ml REAL NOT NULL, price REAL NOT NULL,
            currency TEXT NOT NULL, per_ml REAL NOT NULL, shop TEXT NOT NULL, install TEXT NOT NULL, t INTEGER NOT NULL,
            UNIQUE (install, perfume_id, shop, ml))""")
        t = 1795276026540   # 2026-11-21 UTC
        con.execute("INSERT INTO reports VALUES (30499, 50, 69.99, 'EUR', 1.3998, 'etos.nl', 'abc', ?)", (t,))
        con.commit(); con.close()
        try:
            app.DB_PATH = path
            app.init_db()
            app.init_db()                                   # second start: no duplicates
            with app.db() as c:
                rows = c.execute("SELECT install, perfume_id, shop, ml, currency, day, price FROM daily_lows").fetchall()
            self.assertEqual([tuple(r) for r in rows], [("abc", 30499, "etos.nl", 50.0, "EUR", "2026-11-21", 69.99)])
        finally:
            app.DB_PATH = old

    def test_neighbouring_sizes_only_use_other_shops(self):
        P = 7778
        report(pid=P, ml=50, price=60, shop="etos.nl")
        report(pid=P, ml=100, price=15, shop="etos.nl")   # far off, but only its own shop to compare with
        by = {x["ml"]: x for x in call("GET", f"/prices/{P}")[1]["sizes"]}
        self.assertEqual((by[100]["shops"], by[100]["outliers"]), ({"etos.nl": 0.15}, 0))

    def test_etos_alternatives_block_case(self):
        # The real 2026-11-21 data for perfume 30499: etos.nl stored 4 cards of other perfumes.
        P = 30499
        good = [(10, 22, "notino.nl"), (50, 49.89, "deloox.nl"), (50, 71.99, "douglas.nl"), (50, 60.3, "notino.nl"),
                (90, 65.49, "deloox.nl"), (90, 74.99, "douglas.nl"), (90, 82.2, "notino.nl")]
        bad = [(30, 19.99), (50, 14.99), (75, 25.99), (100, 29.99)]
        for ml, price, shop in good + [(ml, price, "etos.nl") for ml, price in bad]:
            self.assertEqual(report(pid=P, ml=ml, price=price, shop=shop)[0], 201)
        s = call("GET", f"/prices/{P}")[1]
        kept = {(x["ml"], shop) for x in s["sizes"] for shop in x["shops"]}
        self.assertEqual(kept, {(float(ml), shop) for ml, _, shop in good})
        self.assertEqual(sum(x["outliers"] for x in s["sizes"]), 4)

    def test_round2_shops_and_subdomains(self):
        for shop in ("meccabeauty.co.nz", "lebonmarche.com", "24s.com", "saks.com", "jovoyparis.com",
                     "noseparis.com", "spitzenhaus.com", "isetan.mistore.jp", "us.smnovella.com", "eu.smnovella.com"):
            self.assertEqual(report(pid=4242, shop=shop, currency="EUR")[0], 201, shop)
        shops = set(self.size(pid=4242)["shops"])
        self.assertIn("mistore.jp", shops)
        self.assertIn("smnovella.com", shops)
        self.assertNotIn("isetan.mistore.jp", shops)

    def test_same_install_updates_instead_of_adding(self):
        me = str(uuid.uuid4())
        report(price=300, install=me)
        report(price=280, install=me)
        s = call("GET", "/prices/9828")[1]
        self.assertEqual((s["count"], s["median"]), (1, 2.8))

    def test_validation(self):
        bad = [dict(pid="abc"), dict(pid=0), dict(ml=0), dict(ml=5000), dict(price=-1), dict(price="10"),
               dict(price=True), dict(currency="XYZ"), dict(shop="evil.example"), dict(shop="<script>"),
               dict(ml=100, price=1), dict(ml=1, price=1000)]   # last two: implausible per-ml
        for kw in bad:
            self.assertEqual(report(**kw)[0], 422, kw)
        self.assertEqual(call("POST", "/prices", {"perfumeId": 1, "ml": 1, "price": 5, "currency": "EUR",
                                                   "shop": "douglas.nl", "url": "x"}, str(uuid.uuid4()))[0], 422)
        self.assertEqual(report(install="not-a-uuid")[0], 400)
        self.assertEqual(call("POST", "/prices", raw=b"{nope", install=str(uuid.uuid4()))[0], 400)
        self.assertEqual(call("POST", "/prices", raw=b"x" * 2000, install=str(uuid.uuid4()))[0], 413)
        self.assertEqual(report(headers={"Origin": "https://evil.example"})[0], 403)
        code, _, h = report(headers={"Origin": ORIGIN})
        self.assertEqual((code, h["Access-Control-Allow-Origin"]), (201, ORIGIN))

    def test_firefox_origins(self):
        moz = f"moz-extension://{uuid.uuid4()}"
        code, _, h = report(headers={"Origin": moz})
        self.assertEqual((code, h["Access-Control-Allow-Origin"]), (201, moz))
        code, _, h = call("OPTIONS", "/prices", headers={"Origin": moz, "Access-Control-Request-Method": "POST"})
        self.assertEqual((code, h["Access-Control-Allow-Origin"]), (204, moz))
        bad = ["moz-extension://evil", moz.upper().replace("MOZ-EXTENSION", "moz-extension"), moz + "/",
               moz.replace("moz-extension", "https"), "chrome-extension://" + "a" * 32]
        for origin in bad:
            code, _, h = report(headers={"Origin": origin})
            self.assertEqual((code, h.get("Access-Control-Allow-Origin")), (403, None), origin)
            code, _, h = call("OPTIONS", "/prices", headers={"Origin": origin})
            self.assertEqual((code, h.get("Access-Control-Allow-Origin")), (204, None), origin)

    def size(self, ml=100.0, pid=9828):
        return next(s for s in call("GET", f"/prices/{pid}")[1]["sizes"] if s["ml"] == ml)

    def test_odd_first_price_drops_out_once_3_shops_exist(self):
        self.assertEqual(report(price=30, shop="douglas.nl")[0], 201)     # 0.30/ml: odd, but stored
        self.assertEqual(self.size()["shops"], {"douglas.nl": 0.3})
        report(price=300, shop="notino.nl")
        report(price=310, shop="flaconi.de")                               # 3 shops: baseline 3.00
        sz, s = self.size(), call("GET", "/prices/9828")[1]
        self.assertEqual((sz["shops"], sz["outliers"], sz["installs"]), ({"notino.nl": 3.0, "flaconi.de": 3.1}, 1, 2))
        self.assertNotIn("douglas.nl", [c["shop"] for c in s["cheapest"]])
        self.assertEqual((s["min"], s["count"], s["shopCount"]), (3.0, 2, 2))
        report(price=2000, shop="parfumdreams.de")                         # 20/ml: too high, dropped too
        self.assertEqual(self.size()["outliers"], 2)
        with app.db() as con:                                              # nothing was deleted
            self.assertEqual(con.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 4)

    def test_nothing_dropped_with_only_2_shops(self):
        report(price=30, shop="douglas.nl")
        report(price=300, shop="notino.nl")
        sz = self.size()
        self.assertEqual((sz["shops"], sz["outliers"]), ({"douglas.nl": 0.3, "notino.nl": 3.0}, 0))

    def test_label_min_installs_hides_single_install_sizes(self):
        me = str(uuid.uuid4())
        for shop in ("douglas.nl", "notino.nl", "flaconi.de"):
            report(price=300, shop=shop, install=me)
        old = app.LABEL_MIN_INSTALLS
        try:
            app.LABEL_MIN_INSTALLS = 2
            sz = self.size()
            self.assertEqual((sz["shops"], sz["installs"], sz["count"]), ({}, 1, 3))   # other fields stay
            report(price=320, shop="douglas.nl")                                      # a second install
            self.assertEqual(len(self.size()["shops"]), 3)
        finally:
            app.LABEL_MIN_INSTALLS = old

    def test_rate_limit(self):
        me = str(uuid.uuid4())
        codes = [report(pid=1000 + i, ml=50, price=100, install=me)[0] for i in range(61)]
        self.assertEqual(codes[:60], [201] * 60)
        self.assertEqual(codes[60], 429)
        self.assertEqual(report()[0], 201)   # other installs are not affected

    def test_facts_stored_and_counted(self):
        self.assertEqual(fact()[0], 201)
        self.assertEqual(fact(shop="www.notino.nl", name="Stronger With You Absolutely", gender=None)[0], 201)
        s, body, _ = call("GET", "/facts/stats")
        self.assertEqual(s, 200)
        self.assertEqual((body["rows"], body["perfumes"], body["withNotes"], body["gtins"]), (2, 2, 2, 1))
        self.assertEqual(body["shops"], {"douglas.nl": 1, "notino.nl": 1})
        with app.db() as con:
            row = dict(con.execute("SELECT * FROM facts WHERE shop='douglas.nl'").fetchone())
        self.assertEqual(json.loads(row["notes"])["top"], ["Rum", "Bergamot"])
        self.assertNotIn("-", row["install"])        # salted hash, not the install id itself
        self.assertEqual(fact(shop="douglas.de", notes={})[0], 201)   # a shop that lists no notes
        app._facts_stats.update(t=0, data=None)
        body = call("GET", "/facts/stats")[1]
        self.assertEqual((body["rows"], body["withNotes"]), (3, 2))

    def test_same_install_same_day_updates(self):
        install = str(uuid.uuid4())
        fact(install)
        fact(install, notes={"top": ["Rum"], "heart": [], "base": []})
        with app.db() as con:
            rows = con.execute("SELECT notes FROM facts").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][0])["top"], ["Rum"])

    def test_facts_validation(self):
        self.assertEqual(fact(extra=1)[0], 422)
        self.assertEqual(fact(brand="")[0], 422)
        self.assertEqual(fact(name=...)[0], 422)
        self.assertEqual(fact(shop="example.com")[0], 422)
        self.assertEqual(fact(conc="perfume")[0], 422)
        self.assertEqual(fact(gender="x")[0], 422)
        self.assertEqual(fact(gtins=["12ab5678"])[0], 422)
        self.assertEqual(fact(sizes=[50] * 9)[0], 422)
        self.assertEqual(fact(notes={"top": ["x"] * 16})[0], 422)
        self.assertEqual(fact(notes={"middle": []})[0], 422)
        self.assertEqual(fact(name="x" * 121)[0], 422)
        self.assertEqual(fact(perfumeId="abc")[0], 422)
        self.assertEqual(fact(perfumeId=None, conc=None, gender=None, lang=None, gtins=[], families=[])[0], 201)
        big = {**FACT, "families": ["x" * 40] * 6, "notes": {k: ["y" * 40] * 15 for k in ("top", "heart", "base")}}
        self.assertEqual(call("POST", "/facts", big, str(uuid.uuid4()))[0], 201)   # the biggest valid body fits
        raw = json.dumps(FACT).encode() + b" " * 4100
        self.assertEqual(call("POST", "/facts", install=str(uuid.uuid4()), raw=raw)[0], 413)

    def test_facts_origin_and_rate_limit(self):
        self.assertEqual(call("POST", "/facts", FACT, str(uuid.uuid4()), headers={"Origin": "https://evil.example"})[0], 403)
        install = str(uuid.uuid4())
        codes = [fact(install, name=f"Perfume {i}")[0] for i in range(31)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(report()[0], 201)   # prices have their own limits

    def test_old_facts_unlinked_from_installs(self):
        install = str(uuid.uuid4())
        fact(install)
        fact(install, name="Another One")
        old = app.day_of(app.now_ms() - (app.RETENTION_DAYS + 1) * 86400_000)
        with app.db() as con:
            con.execute("UPDATE facts SET day=?", (old,))
        app.purge_old()
        with app.db() as con:
            hashes = [r[0] for r in con.execute("SELECT install FROM facts")]
        self.assertEqual(len(hashes), 2)                     # the facts stay
        self.assertTrue(all(h.startswith("old-") for h in hashes))
        self.assertEqual(len(set(hashes)), 2)                 # and can't be linked to each other
        app._facts_stats.update(t=0, data=None)
        self.assertEqual(call("GET", "/facts/stats")[1]["installs"], 0)   # unlinked rows aren't installs
        app.purge_old()
        with app.db() as con:
            self.assertEqual(sorted(r[0] for r in con.execute("SELECT install FROM facts")), sorted(hashes))

    def test_catalog_endpoints(self):
        fact()
        fact(shop="notino.nl", brand="Giorgio Armani", name="Stronger With You Absolutely", gender=None,
             notes={"top": ["Rum"], "heart": [], "base": []})
        with app.db() as con:
            self.assertEqual(app.catalog.build(con), 1)
        s, body, _ = call("GET", "/catalog/search?q=stronger%20absolutely")
        self.assertEqual(s, 200)
        p = body["results"][0]
        self.assertEqual((p["name"], p["shops"]), ("Stronger With You Absolutely", 2))
        s, full, _ = call("GET", "/catalog/perfume/" + p["id"])
        self.assertEqual(s, 200)
        self.assertTrue(next(n for n in full["notes"]["top"] if n["name"] == "Rum")["confirmed"])
        self.assertEqual(call("GET", "/catalog/perfume/000000000000")[0], 404)
        s, st, _ = call("GET", "/catalog/stats")
        self.assertEqual((st["perfumes"], st["withConfirmedNotes"], st["license"]), (1, 1, "ODbL-1.0"))

    def test_catalog_lookup_is_anonymous(self):
        fact()
        fact(shop="notino.nl", brand="Giorgio Armani", name="Stronger With You Absolutely", gtins=[],
             notes={"top": ["Rum"], "heart": [], "base": []})
        with app.db() as con:
            app.catalog.build(con)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            by_gtin = call("GET", "/catalog/lookup?gtin=3614273642454")
            by_name = call("GET", "/catalog/lookup?brand=Armani&name=Stronger%20With%20You%20Absolutely&conc=parfum&gender=m")
            unknown = call("GET", "/catalog/lookup?brand=Creed&name=Aventus")
        self.assertEqual((by_gtin[0], by_name[0], unknown[0]), (200, 200, 200))
        self.assertEqual(by_gtin[1]["perfume"]["id"], by_name[1]["perfume"]["id"])
        self.assertTrue(next(n for n in by_name[1]["perfume"]["notes"]["top"] if n["name"] == "Rum")["confirmed"])
        self.assertIsNone(unknown[1]["perfume"])
        # The log line has the path only: nothing about which perfume was looked up.
        self.assertIn("GET /catalog/lookup 200", out.getvalue())
        for secret in ("3614273642454", "Stronger", "Creed", "Aventus", "?"):
            self.assertNotIn(secret, out.getvalue())

    def test_no_install_id_stored(self):
        me = str(uuid.uuid4())
        report(install=me)
        with app.db() as con:
            rows = con.execute("SELECT install FROM reports").fetchall()
        self.assertNotIn(me, [r[0] for r in rows])


if __name__ == "__main__":
    unittest.main(verbosity=2)
