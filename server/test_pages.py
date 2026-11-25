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
import urllib.request

TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(TMP, "pages.db")
os.environ["IMG_DIR"] = os.path.join(TMP, "img")
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
            for t in ("facts", "reports", "daily_lows", "page_images", "catalog", "catalog_keys", "catalog_gtins"):
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

    def test_only_perfumes_with_enough_confirmed_notes_get_a_page(self):
        pid = self.pid("Intensely")
        code, body, h = get(f"/perfume/{pid}-armani-stronger-with-you-intensely")
        self.assertEqual(code, 200, body[:300])
        self.assertIn("Stronger With You Intensely", body)
        self.assertIn('class="note ok"', body)
        self.assertIn("Vanilla", body)        # one shop only: shown, not confirmed
        self.assertIn("1 shop", body)
        self.assertIn('rel="canonical"', body)
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
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
        self.assertIn("Wikipedia", body)
        self.assertIn(f"/perfume/{pid}-", body)
        code, body, _ = get("/note/juniper")
        self.assertEqual(code, 200)
        self.assertNotIn("What it smells like", body)     # no reviewed text: facts only
        self.assertEqual(get("/note/vanilla")[0], 404)
        self.assertEqual(get("/note/mandarin")[0], 404)   # only in an unpublished perfume

    def test_database_search_and_sitemap(self):
        code, body, _ = get("/database")
        self.assertEqual(code, 200)
        self.assertIn("Stronger With You Intensely", body)
        self.assertNotIn("Guilty", body)
        self.assertIn("Back to the database", get("/note/tonka-bean")[1])
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
        self.assertIn("Hoe het ruikt", body)
        self.assertIn("cumaruboom", body)                      # the Dutch text from note_texts.json
        self.assertEqual(get("/nl/database")[0], 200)
        self.assertIn("Terug naar de database", get("/nl/notes")[1])
        self.assertEqual(get("/nl")[0], 301)
        self.assertEqual(get("/nl/nothing")[0], 404)

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

    def test_api_still_answers_json(self):
        with urllib.request.urlopen(BASE + "/catalog/stats", timeout=5) as r:
            self.assertIn("perfumes", json.loads(r.read()))
        self.assertEqual(get("/nothing")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
