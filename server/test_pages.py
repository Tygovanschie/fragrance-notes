"""Tests for the public web pages (pages.py), through the real server on a temporary database.
Run: python test_pages.py   (inside the container: docker compose run --rm --no-deps api python test_pages.py)"""
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(TMP, "pages.db")
os.environ["IMG_DIR"] = os.path.join(TMP, "img")
os.environ["NOTE_IMG_DIR"] = os.path.join(TMP, "notes")
import app  # noqa: E402
import catalog  # noqa: E402
import pages  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPEN = urllib.request.build_opener(NoRedirect)


def get(path):
    try:
        with OPEN.open(BASE + path, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers


def add(con, shop, brand, name, top=(), heart=(), base=(), gtins=(), pid=None, conc="edp", gender="m"):
    con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("i-" + shop, "2026-11-24", shop, pid, brand, name, conc, gender, "nl", json.dumps([50, 100]),
                 json.dumps(list(gtins)), json.dumps({"top": list(top), "heart": list(heart), "base": list(base)}), "[]"))


class FakeOBF:
    """Stands in for urllib.request.urlopen: answers the OBF product API and the image download."""
    def __init__(self, image=JPEG, has=True):
        self.image, self.has, self.calls = image, has, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        if "/api/v2/product/" in url:
            if self.has == 404:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b'{"status":0}'))
            body ={"status": 1, "product": {"image_front_url": "https://images.openbeautyfacts.org/x/front.400.jpg"}} \
                if self.has else {"status": 0}
            return io.BytesIO(json.dumps(body).encode())
        return io.BytesIO(self.image)


class PagesTest(unittest.TestCase):
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
            for t in ("facts", "reports", "daily_lows", "page_images", "catalog", "catalog_keys", "catalog_gtins", "votes", "note_images"):
                con.execute(f"DELETE FROM {t}")
            # Published: 4 notes confirmed by two shops.
            for shop in ("douglas.nl", "notino.nl"):
                add(con, shop, "Armani", "Stronger With You Intensely", top=["Roze peper", "Jenever"],
                    heart=["Kaneel"], base=["Tonkaboon", "Vanille"] if shop == "douglas.nl" else ["Tonkaboon"],
                    gtins=["3614272225695"], pid=52802)
            # Not published: only 1 confirmed note.
            for shop in ("douglas.nl", "notino.nl"):
                add(con, shop, "Gucci", "Guilty", top=["Mandarijn"], heart=["Lila"] if shop == "douglas.nl" else [],
                    gtins=["8005610298900"], gender="f")
            # Escaping: a brand with markup, published.
            for shop in ("douglas.nl", "notino.nl"):
                add(con, shop, "<b>Evil</b>", 'Name "<script>x</script>', top=["Bergamot", "Ceder"], base=["Muskus"])
            catalog.build(con)
            con.commit()
        pages._cache["stamp"] = None

    def pid(self, name):
        with app.db() as con:
            return con.execute("SELECT id FROM catalog WHERE name LIKE ?", (f"%{name}%",)).fetchone()[0]

    def test_brand_site_confirms_notes(self):
        # Guilty has 1 confirmed note (no page). Gucci's own site names three more in its text: now it has a page.
        with app.db() as con:
            con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("i-gucci", "2026-11-25", "gucci.com", None, "Gucci", "Guilty", "edp", "f", "en", "[50]", "[]",
                         json.dumps({"top": [], "heart": [], "base": [], "mentioned": ["Lilac", "Peach", "Patchouli"]}), "[]"))
            catalog.build(con)
            con.commit()
        pages._cache["stamp"] = None
        code, body, _ = get(f"/perfume/{self.pid('Guilty')}-gucci-guilty")
        self.assertEqual(code, 200)
        self.assertIn("✓ Confirmed by the brand's own website: gucci.com", body)
        _, nl, _ = get(f"/nl/perfume/{self.pid('Guilty')}-gucci-guilty")
        self.assertIn("Bevestigd door de eigen website van het merk: gucci.com", nl)
        _, other, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertNotIn('class="official"', other)

    def test_only_perfumes_with_enough_confirmed_notes_get_a_page(self):
        pid = self.pid("Intensely")
        code, body, h = get(f"/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertEqual(code, 200, body[:300])
        self.assertIn("Stronger With You Intensely", body)
        self.assertIn('class="tile"', body)
        self.assertIn("Vanilla", body)        # one shop only: shown, not confirmed
        self.assertIn("Also named by one shop (1)", body)   # not in the pyramid, in the list underneath
        self.assertIn("Vanilla <small>(douglas.nl)</small>", body)
        self.assertNotIn('class="note one"', body)
        self.assertIn('rel="canonical"', body)
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertIn("script-src 'self';", h["Content-Security-Policy"])                 # only our own file, no inline code
        self.assertEqual(re.findall(r'<script(?! type="application/ld\+json")', body), [])   # only the JSON-LD data block
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', body).group(1))
        self.assertEqual((ld["@type"], ld["name"], ld["brand"]["name"]), ("Product", "Stronger With You Intensely", "Armani"))
        self.assertIn('hreflang="nl"', body)
        code, body, _ = get(f"/perfume/{self.pid('Guilty')}")
        self.assertEqual(code, 404)
        self.assertIn("noindex", body)

    def test_wrong_slug_redirects_to_the_canonical_path(self):
        pid = self.pid("Intensely")
        code, _, h = get(f"/perfume/{pid}")
        self.assertEqual(code, 301)
        self.assertEqual(h["Location"], f"/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertEqual(get("/perfume/000000000000-x")[0], 404)
        self.assertEqual(get("/perfume/../../etc/passwd")[0], 404)

    def test_values_are_escaped(self):
        code, body, _ = get(f"/perfume/{self.pid('script')}")
        self.assertEqual(code, 301)
        code, body, _ = get(get(f"/perfume/{self.pid('script')}")[2]["Location"])
        self.assertEqual(code, 200)
        self.assertNotIn("<script>x", body)
        self.assertNotIn("<b>Evil</b>", body)
        self.assertIn("&lt;b&gt;Evil&lt;/b&gt;", body)

    def test_note_pages_and_links(self):
        pid = self.pid("Intensely")
        _, body, _ = get(f"/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertIn('href="/note/tonka-bean"', body)
        self.assertIn('href="/note/pink-pepper"', body)
        self.assertNotIn('href="/note/vanilla"', body)     # vanilla is confirmed nowhere: no page
        code, body, _ = get("/note/tonka-bean")
        self.assertEqual(code, 200)
        self.assertIn("Tonka bean", body)
        self.assertIn("Tonkaboon", body)                  # how shops write it
        self.assertIn("Dipteryx odorata", body)           # the reviewed text from note_texts.json
        # The extension's note pop-up: found by any spelling a shop uses, the page in the panel's language.
        n = json.loads(get("/catalog/note?key=Tonkaboon&lang=nl")[1])["note"]
        self.assertEqual((n["key"], n["url"]), ("tonka bean", "https://fragrancenotes.app/nl/note/tonka-bean"))
        self.assertIn("Dipteryx odorata", n["origin"] + n["smell"])
        self.assertIn("Wikipedia", body)
        self.assertIn(f"/perfume/{pid}-", body)
        code, body, _ = get("/note/juniper")
        self.assertEqual(code, 200)
        self.assertNotIn("notesmell", body)     # no reviewed text: facts only
        self.assertEqual(get("/note/vanilla")[0], 404)
        self.assertEqual(get("/note/mandarin")[0], 404)   # only in an unpublished perfume

    def test_database_search_and_sitemap(self):
        code, body, _ = get("/database")
        self.assertEqual(code, 200)
        self.assertIn("Stronger With You Intensely", body)
        self.assertNotIn("Guilty", body)
        self.assertLess(body.index('id="perfumes"'), body.index('class="stats"'))     # perfumes first, then numbers
        self.assertLess(body.index('class="stats"'), body.index('class="part how"'))
        self.assertIn('class="astrip mini"', body)                                      # accord strip on each card
        self.assertEqual(body.count('class="pcard"'), body.count('<div class="pimg">'))              # every card has its square
        self.assertIn('<span class="ph" style="background:linear-gradient(140deg,', body)              # no photo: accord colours
        self.assertNotIn('class="pcard soon"', body)                                     # no card left alone in a row
        self.assertIn('<form class="listsearch" role="search" action="/database">', body)    # search under "All perfumes"
        self.assertNotIn('class="hsearch"', body)                                           # not twice on this page
        self.assertIn('<form class="hsearch" role="search" action="/nl/database/search">', get("/nl/note/tonka-bean")[1])
        self.assertIn('<script src="/assets/live.js?v=', body)
        self.assertNotIn("<small>", body.split('id="perfumes"')[1].split("</h2>")[0])        # no count next to the title
        # The search filters the same page (also without the script), and pages keep the words.
        _, found, _ = get("/database?q=stronger")
        self.assertIn("Stronger With You Intensely", found)
        self.assertIn("noindex", found)
        _, found, _ = get("/database?q=tonka")                                               # by note, too
        self.assertIn("Stronger With You Intensely", found)
        _, none, _ = get("/database?q=zzzz")
        self.assertIn('class="nomatch"', none)
        self.assertEqual(pages.db_link("en", 48, 2, "tom ford"), "/database?q=tom+ford&amp;show=48&amp;page=2#perfumes")
        with urllib.request.urlopen(BASE + "/assets/live.js", timeout=5) as r:
            self.assertIn("listsearch", r.read().decode())
        self.assertEqual(get("/database?show=48&page=2")[0], 200)
        self.assertEqual(get("/database?show=abc&page=x")[0], 200)
        self.assertTrue(all(n % 12 == 0 for n in pages.SHOW_STEPS))                       # full rows in 1-4 columns
        self.assertEqual(pages.database_page(app.db(), None, "en", 7).count('class="pcard"'),
                         min(24, len(pages.index(app.db())["perfumes"])))                 # unknown count: 24
        self.assertIn("← All perfumes", get("/note/tonka-bean")[1])
        # Page numbers: 30 perfumes in pages of 24 → 2 pages; 100 → 1 … around the current one … 5.
        self.assertEqual(pages.pager("en", 24, 1, 1), "")
        p = pages.pager("en", 24, 1, 2)
        self.assertIn('aria-current="page">1<', p)
        self.assertIn('href="/database?page=2#perfumes" rel="next">Next →', p)
        p = pages.pager("en", 48, 5, 9)
        self.assertEqual(re.findall(r">(\d+|…)<", p), ["1", "…", "3", "4", "5", "6", "7", "…", "9"])
        self.assertIn('href="/database?show=48&amp;page=4#perfumes" rel="prev"', p)
        code, body, _ = get("/database/search?q=stronger")
        self.assertEqual(code, 200)
        self.assertIn("Stronger With You Intensely", body)
        self.assertIn("noindex", body)
        code, body, _ = get("/database/search?q=guilty")
        self.assertIn("1 more perfume", body)
        _, body, _ = get("/database/search?q=%3Cscript%3E")
        self.assertNotIn("<script>", body)
        code, body, h = get("/sitemap.xml")
        self.assertEqual(code, 200)
        self.assertIn("/perfume/", body)
        self.assertIn("/note/tonka-bean", body)
        self.assertNotIn(self.pid("Guilty"), body)
        code, body, h = get("/assets/pages.css")
        self.assertEqual(code, 200)
        self.assertIn("text/css", h["Content-Type"])

    def test_prices_on_the_page(self):
        now = int(time.time() * 1000)
        with app.db() as con:
            for shop, price in (("zalando.nl", 68.95), ("douglas.nl", 74.95), ("notino.nl", 69.52)):
                con.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)", (52802, 100, price, "EUR", price / 100, shop, "h-" + shop, now))
            con.commit()
        _, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertIn("Prices", body)
        self.assertIn("€68.95", body)
        self.assertIn("zalando.nl", body)
        self.assertIn("100 ml at each shop", body)
        self.assertIn("€68.95", get("/database")[1])
        self.assertNotIn('class="szpick"', body)   # one size: nothing to pick

    def test_prices_per_country(self):
        import regions
        self.assertEqual(regions.country_of("douglas.nl", "EUR"), "NL")
        self.assertEqual(regions.country_of("tomfordbeauty.com", "USD"), "US")
        self.assertEqual(regions.country_of("tomfordbeauty.com", "EUR"), "EU")      # euros, country unknown
        self.assertEqual(regions.country_of("notino.co.uk", "GBP"), "GB")
        self.assertEqual(regions.country_of("ulta.com", "USD"), "US")
        self.assertEqual(regions.country_of("douglas.de", "USD"), "US")              # the currency wins
        now = int(time.time() * 1000)
        with app.db() as con:
            for shop, cur, price in (("douglas.nl", "EUR", 79.0), ("notino.nl", "EUR", 75.5), ("tomfordbeauty.com", "USD", 120.0),
                                     ("ulta.com", "USD", 115.0)):
                con.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)", (52802, 100, price, cur, price / 100, shop, "c-" + shop, now))
            con.commit()
        page = f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely"
        _, nl, _ = get(page + "?vc=NL")
        self.assertIn("€75.50", nl)
        self.assertNotIn("$", nl.split('id="prices"')[1].split("</section>")[0])     # never dollars for a Dutch visitor
        _, us, _ = get(page + "?vc=US")
        self.assertIn("$115.00", us)
        self.assertNotIn("€75.50", us)
        _, de, _ = get(page + "?vc=DE")                                              # no German shop: the eurozone
        self.assertIn("€75.50", de)
        self.assertIn("No shop in \U0001F1E9\U0001F1EA DE yet", de)
        _, jp, _ = get(page + "?vc=JP")                                              # nothing in yen: say so
        self.assertIn("No prices for \U0001F1EF\U0001F1F5 JP yet", jp)
        self.assertNotIn("$115.00", jp)
        _, picked, _ = get(page + "?vc=NL&region=US")                                # the visitor's own choice wins
        self.assertIn("$115.00", picked)
        self.assertIn('href="' + page + '?region=US#prices" aria-current="true"', picked)
        _, cards, _ = get("/database?vc=NL")
        self.assertIn("€75.50", cards)
        self.assertNotIn("$115.00", cards)

    def test_price_size_picker(self):
        now = int(time.time() * 1000)
        with app.db() as con:
            for shop, ml, price in (("zalando.nl", 30, 39.95), ("douglas.nl", 50, 59.95), ("notino.nl", 50, 57.5),
                                    ("deloox.nl", 100, 79.0)):
                con.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)", (52802, ml, price, "EUR", price / ml, shop, "s-" + shop, now))
            con.commit()
        _, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        pick = re.search(r'<div class="szpick"[^>]*>(.*?)</div>', body).group(1)
        self.assertEqual(re.findall(r">(\d+ ml)<", pick), ["30 ml", "50 ml", "100 ml"])   # every size can be picked
        self.assertEqual(body.count('class="szp"'), 3)
        for size in ("30 ml", "50 ml", "100 ml"):
            self.assertIn(f"{size} at each shop", body)
        radios = re.findall(r'<input class="sr" type="radio" name="sz[0-9a-f]+" id="sz[0-9a-f]+-(\d)"( checked)?>', body)
        self.assertEqual([i for i, c in radios if c], ["1"])                # starts on 50 ml: the most shops
        self.assertIn(".sizes input:nth-of-type(3):checked~.szp:nth-of-type(3){display:block}", pages.CSS)

    def test_photos_from_open_beauty_facts(self):
        fake = FakeOBF()
        with app.db() as con:
            self.assertEqual(pages.refresh_images(con, opener=fake), 1)
            self.assertEqual(pages.refresh_images(con, opener=fake), 0)    # has one: no new lookups
        self.assertTrue(any("3614272225695" in c for c in fake.calls))
        self.assertFalse(any("8005610298900" in c for c in fake.calls))   # unpublished: never looked up
        code, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertIn('src="/photo/3614272225695.jpg"', body)
        self.assertIn("Open Beauty Facts</a>, CC BY-SA", body)
        with urllib.request.urlopen(BASE + "/photo/3614272225695.jpg", timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "image/jpeg")
            self.assertEqual(r.read(), JPEG)
        self.assertEqual(get("/photo/..%2Fpages.db")[0], 404)
        self.assertEqual(get("/photo/x.jpg")[0], 404)

    def test_no_photo_or_not_an_image(self):
        with app.db() as con:
            fake = FakeOBF(image=b"<html>nope</html>")
            self.assertEqual(pages.refresh_images(con, opener=fake), 0)
            n = len(fake.calls)
            pages.refresh_images(con, opener=fake)                          # checked: wait IMG_RECHECK
            self.assertEqual(len(fake.calls), n)
            pages.refresh_images(con, opener=fake, now=time.time() + pages.IMG_RECHECK + 1)
            self.assertGreater(len(fake.calls), n)
        _, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertNotIn("/photo/", body)
        with app.db() as con:   # "not found" from Open Beauty Facts counts as checked, not as a network error
            con.execute("DELETE FROM page_images")
            fake = FakeOBF(has=404)
            pages.refresh_images(con, opener=fake)
            n = len(fake.calls)
            pages.refresh_images(con, opener=fake)
            self.assertEqual(len(fake.calls), n)

    def test_dutch_pages(self):
        pid = self.pid("Intensely")
        code, body, _ = get(f"/nl/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertEqual(code, 200)
        self.assertIn('<html lang="nl">', body)
        self.assertIn("Geurnoten", body)
        self.assertIn('href="/nl/note/tonka-bean"', body)
        self.assertIn(">Tonkaboon<", body)                     # the note's Dutch name
        self.assertIn('hreflang="en"', body)
        code, _, h = get(f"/nl/perfume/{pid}")
        self.assertEqual((code, h["Location"]), (301, f"/nl/perfume/{pid}-armani-stronger-with-you-intensely"))
        code, body, _ = get("/nl/note/tonka-bean")
        self.assertEqual(code, 200)
        self.assertIn("Hoe het ruikt", body)                   # how it smells: its own card next to the photo
        self.assertIn("cumaruboom", body)                      # the Dutch text from note_texts.json
        self.assertEqual(get("/nl/database")[0], 200)
        self.assertIn("← Alle parfums", get("/nl/notes")[1])
        self.assertEqual(get("/nl")[0], 301)
        self.assertEqual(get("/nl/nothing")[0], 404)
        # The other languages, and the language menu on every page.
        for lang, word in (("de", "Duftnoten"), ("fr", "Notes"), ("es", "Notas"), ("it", "Note"), ("pt", "Notas"), ("pl", "Nuty")):
            code, body, _ = get(f"/{lang}/perfume/{pid}-armani-stronger-with-you-intensely")
            self.assertEqual(code, 200, lang)
            self.assertIn(f'<html lang="{lang}">', body)
            self.assertIn(f">{word}<", body)
            self.assertIn(f'href="/{lang}/perfume/{pid}-armani-stronger-with-you-intensely" hreflang="{lang}" lang="{lang}" aria-current="true"', body)
        _, body, _ = get("/database")
        for lang in ("nl", "de", "fr", "es", "it", "pt", "pl"):
            self.assertIn(f'href="/{lang}/database"', body)
        self.assertIn("€1.234,50", pages.money(1234.5, "EUR", "de"))

    def test_brand_and_notes_pages(self):
        code, body, _ = get("/brand/armani")
        self.assertEqual(code, 200)
        self.assertIn("Stronger With You Intensely", body)
        self.assertIn('"@type": "Brand"', body)
        self.assertEqual(get("/brand/gucci")[0], 404)          # no published perfume
        code, body, _ = get("/notes")
        self.assertEqual(code, 200)
        self.assertIn('href="/note/tonka-bean"', body)
        self.assertNotIn('href="/note/mandarin"', body)
        _, body, _ = get("/database")
        self.assertIn('href="/brand/armani"', body)
        self.assertIn('"@type": "Dataset"', body)
        _, body, _ = get("/sitemap.xml")
        self.assertIn("/nl/perfume/", body)
        self.assertIn("/brand/armani", body)
        self.assertIn('hreflang="nl"', body)

    def test_price_chart(self):
        now = int(time.time() * 1000)
        with app.db() as con:
            con.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)", (52802, 100, 68.95, "EUR", .6895, "zalando.nl", "h-z", now))
            for i, price in enumerate((79.0, 74.5, 68.95)):
                d = time.strftime("%Y-%m-%d", time.gmtime(time.time() - (2 - i) * 86400))
                con.execute("INSERT INTO daily_lows VALUES (?,?,?,?,?,?,?,?)", ("h-z", 52802, "zalando.nl", 100, "EUR", d, price, now))
            con.commit()
        _, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertIn("day by day", body)
        self.assertIn("<polyline", body)
        self.assertIn("from €68.95 to €79.00", body)
        self.assertIn('"lowPrice": "68.95"', body)
        _, body, _ = get(f"/nl/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertIn("van €68,95 tot €79,00", body)

    def vote(self, pid, form, cookie=None, origin="https://fragrancenotes.app", lang=""):
        data = urllib.parse.urlencode(form).encode()
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        if origin:
            h["Origin"] = origin
        if cookie:
            h["Cookie"] = cookie
        req = urllib.request.Request(f"{BASE}{lang}/perfume/{pid}/vote", data=data, method="POST", headers=h)
        try:
            with OPEN.open(req, timeout=5) as r:
                return r.status, r.headers
        except urllib.error.HTTPError as err:
            return err.code, err.headers

    def test_voting(self):
        pid = self.pid("Intensely")
        page = f"/perfume/{pid}-armani-stronger-with-you-intensely"
        _, body, _ = get(page)
        self.assertIn(f'action="/perfume/{pid}/vote"', body)
        self.assertIn("No votes yet", body)
        # The "owns" box is required, and at least one answer.
        code, h = self.vote(pid, {"rating": "5"})
        self.assertEqual((code, h["Location"]), (303, page + "?vote=own#vote"))
        self.assertEqual(self.vote(pid, {"owns": "1"})[1]["Location"], page + "?vote=empty#vote")
        self.assertEqual(self.vote(pid, {"owns": "1", "sillage": "9"})[1]["Location"], page + "?vote=empty#vote")
        # A first vote sets the cookie; voting again with it changes the vote instead of adding one.
        code, h = self.vote(pid, {"owns": "1", "rating": "4", "longevity": "3", "gender": "5"})
        self.assertEqual((code, h["Location"]), (303, page + "?vote=thanks#vote"))
        cookie = h["Set-Cookie"].split(";")[0]
        self.assertRegex(cookie, r"^fn_voter=[0-9a-f]{32}$")
        self.assertIn("HttpOnly", h["Set-Cookie"])
        code, h = self.vote(pid, {"owns": "1", "rating": "5"}, cookie=cookie)
        self.assertEqual(code, 303)
        self.assertIsNone(h["Set-Cookie"])
        with app.db() as con:
            rows = con.execute("SELECT voter, rating, longevity FROM votes").fetchall()
        self.assertEqual([(r[1], r[2]) for r in rows], [(5, 3)])           # rating changed, longevity kept
        self.assertNotIn(cookie.split("=")[1], rows[0][0])                # only the hash is stored
        code, body, h = get(page + "?vote=thanks")
        self.assertIn("Thanks! Your vote is in", body)
        self.assertEqual(h["Cache-Control"], "private, no-store")
        self.assertIn("from 1 vote", body)                               # results from the first vote
        self.assertIn('<span class="big">5.0</span>', body)
        self.assertNotIn('"aggregateRating"', body)                       # for search engines only from 3
        # With the cookie: the own answers filled in, a "saved" note, and never cached.
        req = urllib.request.Request(BASE + page, headers={"Cookie": cookie})
        with OPEN.open(req, timeout=5) as r:
            mine, hdr = r.read().decode(), r.headers
        self.assertIn("Your vote is saved", mine)
        self.assertIn('id="r5" value="5" checked', mine)
        self.assertIn('id="longevity3" value="3" checked', mine)
        self.assertIn("Update my vote", mine)
        self.assertEqual(hdr["Cache-Control"], "private, no-store")
        # The Google rating appears from 3 voters.
        for r in ("3", "4"):
            self.vote(pid, {"owns": "1", "rating": r, "sillage": "2"})
        _, body, _ = get(page)
        self.assertIn('<span class="big">4.0</span>', body)
        self.assertIn('<label for="sillage2">Moderate</label>', body)          # one word per sillage step
        self.assertIn('<div class="vcell best"><span class="vcol" aria-hidden="true"><i style="--h:100%"></i></span>'
                      '<b>2</b><span class="l" title="Moderate">Moderate</span></div>', body)
        self.assertIn('class="vlist"', body)
        # The answers from least to most, left to right: Intimate first, Scent trail last.
        row = re.search(r'<h3>Sillage</h3><div class="vrow">(.*?)</div></div>', body).group(1)
        self.assertEqual(re.findall(r'title="([^"]+)"', row), ["Intimate", "Moderate", "Enveloping", "Room-filling", "Scent trail"])
        self.assertIn("<h3>Sillage</h3>", body)
        self.assertIn('"aggregateRating"', body)
        # Dutch page, other origin, unknown perfume.
        _, body, _ = get("/nl" + page)
        self.assertIn("Jouw stem", body)
        self.assertEqual(self.vote(pid, {"owns": "1", "rating": "5"}, lang="/nl")[1]["Location"], "/nl" + page + "?vote=thanks#vote")
        self.assertEqual(self.vote(pid, {"owns": "1", "rating": "1"}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.vote(pid, {"owns": "1", "rating": "1"}, origin=None)[0], 403)
        # A perfume without a page yet: its rating page (not indexed) takes votes too.
        gid = self.pid("Guilty")
        code, body, _ = get(f"/perfume/{gid}/rate")
        self.assertEqual(code, 200)
        self.assertIn("noindex", body)
        self.assertIn(f'action="/perfume/{gid}/vote"', body)
        self.assertEqual(self.vote(gid, {"owns": "1", "rating": "2"})[1]["Location"], f"/perfume/{gid}/rate?vote=thanks#vote")
        code, _, h = get(f"/perfume/{pid}/rate")
        self.assertEqual((code, h["Location"]), (301, page + "#vote"))
        self.assertEqual(get("/perfume/000000000000/rate")[0], 404)
        self.assertEqual(self.vote("000000000000", {"owns": "1", "rating": "1"})[0], 404)

    def test_main_accords(self):
        import accords
        p = {"notes": {"top": [{"en": "pink pepper", "confirmed": True}, {"en": "juniper", "confirmed": True}],
                       "heart": [{"en": "cinnamon", "confirmed": True}],
                       "base": [{"en": "tonka bean", "confirmed": True}, {"en": "vanilla", "confirmed": False}]},
             "families": [{"key": "spicy", "confirmed": True}]}
        acc = accords.main_accords(p)
        self.assertEqual(acc[0][1], 100)
        self.assertIn("warm spicy", dict(acc))
        self.assertTrue(all(v >= accords.MIN_SHOWN for _, v in acc))
        self.assertEqual(accords.main_accords({"notes": {"top": [{"en": "vanilla", "confirmed": True}]}}), [])   # too few notes
        self.assertTrue(set(accords.NOTES) <= set(catalog.NOTE_EN))      # only notes the dictionary has
        for m in list(accords.NOTES.values()) + list(accords.FAMILIES.values()):
            self.assertTrue(set(m) <= set(accords.COLOURS))
        for lang in pages.LANGS:
            self.assertEqual(set(accords.NAMES[lang]), set(accords.COLOURS), lang)
        _, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertIn("Main accords", body)
        self.assertIn('class="astrip"', body)
        pct = [int(x) for x in re.findall(r'<li><i style="--c:#[0-9a-f]{6}"></i>[^<]+<small>(\d+)%</small></li>', body)]
        self.assertGreater(len(pct), 1)
        self.assertEqual(sum(pct), 100)                                    # shares, not "strength of the top one"
        self.assertEqual(pct, sorted(pct, reverse=True))
        self.assertEqual(pages.shares([("a", 100), ("b", 100), ("c", 100)]), [("a", 34), ("b", 33), ("c", 33)])
        self.assertEqual(pages.shares([]), [])
        _, body, _ = get(f"/nl/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertIn("Hoofdaccoorden", body)

    def test_photos_from_other_sources(self):
        pid = self.pid("Intensely")

        def sites(req, timeout=None):
            u = req.full_url
            if "openbeautyfacts.org/api" in u:
                raise urllib.error.HTTPError(u, 404, "Not Found", {}, io.BytesIO(b"{}"))
            if "openproductsfacts.org/api" in u:   # only the sister project has it, in another language
                return io.BytesIO(json.dumps({"status": 1, "product": {"selected_images": {"front": {"display": {
                    "fr": "https://images.openproductsfacts.org/x/front_fr.400.jpg"}}}}}).encode())
            if "openfoodfacts.org/api" in u:
                raise urllib.error.HTTPError(u, 404, "Not Found", {}, io.BytesIO(b"{}"))
            return io.BytesIO(JPEG)

        with app.db() as con:
            self.assertEqual(pages.refresh_images(con, opener=sites, approved={}), 1)
        _, body, _ = get(f"/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertIn('href="https://world.openproductsfacts.org/product/3614272225695">Open Products Facts</a>, CC BY-SA', body)

        # No Open Facts photo at all: the Commons photo approved in perfume_photos.json, with its credit.
        def commons(req, timeout=None):
            u = req.full_url
            if "/api/v2/product/" in u:
                raise urllib.error.HTTPError(u, 404, "Not Found", {}, io.BytesIO(b"{}"))
            if "commons.wikimedia.org" in u:
                return io.BytesIO(json.dumps({"query": {"pages": {"-1": {"imageinfo": [{
                    "thumburl": "https://upload.wikimedia.org/x/400px-Bottle.jpg", "url": "https://upload.wikimedia.org/x/Bottle.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Bottle.jpg", "mime": "image/jpeg",
                    "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}, "Artist": {"value": "Sam Photo"},
                                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0"}}}]}}}}).encode())
            return io.BytesIO(JPEG)

        with app.db() as con:
            con.execute("DELETE FROM page_images")
            self.assertEqual(pages.refresh_images(con, opener=commons, approved={pid: "Bottle.jpg"}), 1)
        _, body, _ = get(f"/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertIn(f'src="/photo/c-{pid}.jpg"', body)
        self.assertIn("Sam Photo", body)
        self.assertIn('Wikimedia Commons</a>', body)
        with urllib.request.urlopen(f"{BASE}/photo/c-{pid}.jpg", timeout=5) as r:
            self.assertEqual(r.read(), JPEG)

    def test_nightly_maintenance(self):
        import maintenance
        old = maintenance.AUTO_DB
        with tempfile.TemporaryDirectory() as d:
            maintenance.AUTO_DB = os.path.join(d, "auto.db")
            try:
                self.assertEqual(maintenance.aliases(), {})          # no file yet: nothing learned, nothing breaks
                self.assertEqual(maintenance.week()["changes"], [])
                con = maintenance.open_rw()
                day = time.strftime("%Y-%m-%d")
                con.execute("INSERT INTO note_alias VALUES ('kardemonn', 'cardamom', ?)", (day,))
                con.execute("INSERT INTO note_text VALUES ('juniper', 'Warm, sweet and almondy.', 'Seeds of a tree.', "
                            "'https://en.wikipedia.org/wiki/Tonka_bean', ?)", (day,))
                con.execute("INSERT INTO changes VALUES (?, 'note name', 'Kardemonn', 'now read as cardamom')", (day,))
                con.execute("INSERT INTO todo VALUES (?, 'same perfume?', 'Armani: A = B', 'edp')", (day,))
                con.commit()
                con.close()
                # A spelling the job learned is read as the known note at the next rebuild.
                with app.db() as db:
                    add(db, "deloox.nl", "Armani", "Stronger With You Intensely", top=["Kardemonn"], pid=52802)
                    add(db, "kruidvat.nl", "Armani", "Stronger With You Intensely", top=["Kardemom"], pid=52802)
                    catalog.build(db)
                    db.commit()
                    p = catalog.perfume(db, self.pid("Intensely"))
                keys = [n["key"] for t in p["notes"].values() for n in t]
                self.assertIn("cardamom", keys)
                self.assertNotIn("kardemonn", keys)
                # Its note text is on the note page; the weekly summary lists both lists.
                pages._cache["stamp"] = None
                _, body, _ = get("/note/juniper")
                self.assertIn("Warm, sweet and almondy.", body)
                self.assertIn("checked against it automatically", body)          # honest: not checked by hand
                self.assertNotIn("Warm, sweet and almondy.", get("/note/tonka-bean")[1] or "")   # hand-made text wins
                # A text without an origin (it failed its checks) or a source: only the smell, and an honest credit.
                con = maintenance.open_rw()
                con.execute("UPDATE note_text SET origin='', source='' WHERE key='juniper'")
                con.commit()
                con.close()
                pages._auto.update(mtime=None, texts={})
                pages._cache["stamp"] = None
                _, body, _ = get("/note/juniper")
                self.assertIn("Warm, sweet and almondy.", body)
                self.assertNotIn("Seeds of a tree.", body)
                self.assertNotIn(pages.T["en"]["comesFrom"], body)
                self.assertIn("checked automatically against our perfume data", body)
                with urllib.request.urlopen(BASE + "/maintenance/week", timeout=5) as r:
                    w = json.loads(r.read())
                self.assertEqual([c["item"] for c in w["changes"]], ["Kardemonn"])
                self.assertEqual([t["kind"] for t in w["todo"]], ["same perfume?"])
            finally:
                maintenance.AUTO_DB = old
                pages._auto.update(mtime=None, texts={})
                with app.db() as db:
                    catalog.build(db)
                    db.commit()

    def test_note_photos(self):
        import notephotos
        # Fallback photos from the article: real photos yes; maps, satellite views, molecules, drawings no.
        for name, ok in [("Apricots.jpg", True), ("Large_breaking_wave.jpg", True), ("Blood_orange_slices.jpg", True),
                         ("Mediterranean_Sea_16.61811E_38.99124N.jpg", False), ("Coriander distribution map.jpg", False),
                         ("Vanillin structure.svg", False), ("Köhler's Medizinal-Pflanzen 1887.jpg", False),
                         ("Pacific Ocean as viewed from GOES-18.jpg", False)]:
            self.assertEqual(notephotos.usable(name), ok, name)

        def commons(license):
            def opener(req, timeout=None):
                u = req.full_url
                if "en.wikipedia.org" in u:
                    return io.BytesIO(json.dumps({"query": {"pages": {"1": {"pageimage": "Tonka.jpg"}}}}).encode())
                if "commons.wikimedia.org" in u:
                    return io.BytesIO(json.dumps({"query": {"pages": {"-1": {"imageinfo": [{
                        "thumburl": "https://upload.wikimedia.org/x/400px-Tonka.jpg", "url": "https://upload.wikimedia.org/x/Tonka.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Tonka.jpg", "mime": "image/jpeg",
                        "extmetadata": {"LicenseShortName": {"value": license}, "Artist": {"value": "<a href='x'>Jane Doe</a>"},
                                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}}]}}}}).encode())
                return io.BytesIO(JPEG)
            return opener

        with app.db() as con:
            self.assertEqual(notephotos.refresh(con, ["tonka bean", "musk"], opener=commons("CC BY-NC-SA 2.0")), 0)   # not free
            con.execute("DELETE FROM note_images")
            self.assertEqual(notephotos.refresh(con, ["tonka bean", "musk"], opener=commons("CC BY-SA 4.0")), 1)
            self.assertIsNone(con.execute("SELECT 1 FROM note_images WHERE key='musk'").fetchone())   # animal note: skipped
            ph = notephotos.get(con, "tonka bean")
        self.assertEqual((ph["file"], ph["artist"], ph["license"]), ("tonka-bean.jpg", "Jane Doe", "CC BY-SA 4.0"))
        _, body, _ = get("/note/tonka-bean")
        self.assertRegex(body, r'src="/photo/n/tonka-bean\.jpg\?v=[0-9a-f]+"')
        self.assertIn("Jane Doe", body)
        self.assertIn("Wikimedia Commons</a>", body)
        self.assertNotIn('class="swatch"', body)
        _, body, _ = get(f"/perfume/{self.pid('Intensely')}-armani-stronger-with-you-intensely")
        self.assertRegex(body, r'<span class="nimg"><img src="/photo/n/tonka-bean\.jpg\?v=[0-9a-f]+"')
        v1 = re.search(r'/photo/n/tonka-bean\.jpg\?v=([0-9a-f]+)', body).group(1)
        self.assertIn("Note photos: Wikimedia Commons", body)
        with urllib.request.urlopen(BASE + "/photo/n/tonka-bean.jpg?v=1", timeout=5) as r:
            self.assertEqual(r.read(), JPEG)
        for name in ("Piper_nigrum_-_Köhler–s_Medizinal-Pflanzen-107.jpg", "Ficus_carica_L,_1771.jpg",
                     "Orange_Blossom_(NGM_XXXI_p504).jpg"):
            self.assertTrue(notephotos.DRAWING.search(name.replace("_", " ")), name)
        for name in ("Bergamot_orange_-_whole_and_slice.jpg", "Vetiver_grass.jpg", "02017_0119_Kardamom,_Winter_in_den_Beskiden.jpg"):
            self.assertFalse(notephotos.DRAWING.search(name.replace("_", " ")), name)
        # A file picked by hand in FILES replaces the stored photo right away (no 30-day wait), and when that file
        # isn't free the photo we have stays.
        old = dict(notephotos.FILES)
        try:
            notephotos.FILES["tonka bean"] = "Tonka beans.jpg"
            with app.db() as con:
                self.assertEqual(notephotos.refresh(con, ["tonka bean"], opener=commons("CC BY-NC 2.0")), 0)
                self.assertIsNotNone(notephotos.get(con, "tonka bean"))
                self.assertEqual(notephotos.refresh(con, ["tonka bean"], opener=commons("CC0"), now=time.time() + 60), 1)
                self.assertEqual(con.execute("SELECT title FROM note_images WHERE key='tonka bean'").fetchone()[0], "Tonka beans.jpg")
                self.assertNotIn(f"?v={v1}", notephotos.get(con, "tonka bean")["url"])   # new address: no stale browser copy
                self.assertEqual(notephotos.refresh(con, ["tonka bean"], opener=commons("CC0")), 0)   # done: not again
        finally:
            notephotos.FILES.clear()
            notephotos.FILES.update(old)
        self.assertEqual(get("/photo/n/..%2F..%2Fpages.db")[0], 404)

    def test_api_still_answers_json(self):
        with urllib.request.urlopen(BASE + "/catalog/stats", timeout=5) as r:
            self.assertIn("perfumes", json.loads(r.read()))
        self.assertEqual(get("/nothing")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
