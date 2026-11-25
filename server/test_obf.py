"""Tests for the Open Beauty Facts import (obf.py) and how the catalog uses it. Run: python test_obf.py"""
import gzip
import io
import json
import sqlite3
import unittest

import catalog
import obf
from test_catalog import add, db

LINES = [
    # a perfume with category, barcode, quantity and the concentration in the name
    {"code": "4006381333931", "product_name": "Aventus Eau de Parfum 100 ml", "brands": "Creed",
     "quantity": "100 ml", "categories_tags": ["en:beauty", "en:perfumes", "en:eaux-de-parfum"], "lang": "fr",
     "last_modified_t": 1700000000},
    # the name only in another language field, size in fl oz, men's category
    {"code": "0012345678905", "product_name_en": "Sauvage", "brands": "Dior, Parfums Christian Dior",
     "quantity": "3.4 fl oz", "categories_tags": ["en:perfumes", "en:eaux-de-toilette", "en:perfumes-for-men"],
     "lang": "en", "last_modified_t": 1700000001},
    # not a perfume: shampoo
    {"code": "4006381333931", "product_name": "Shampoo", "brands": "X", "categories_tags": ["en:shampoos"]},
    # bad barcode
    {"code": "1234", "product_name": "Something", "brands": "Y", "categories_tags": ["en:perfumes"]},
    # no brand
    {"code": "4006381333948", "product_name": "Nameless", "categories_tags": ["en:perfumes"]},
]


def export(lines):
    raw = gzip.compress(("\n".join(json.dumps(x) for x in lines) + "\nnot json\n").encode())
    return lambda req, timeout=None: io.BytesIO(raw)


class Import(unittest.TestCase):
    def test_keeps_only_usable_perfumes(self):
        con = db()
        self.assertEqual(obf.run(con, opener=export(LINES)), (6, 2))
        rows = {r[0]: r for r in con.execute("SELECT code, brand, name, conc, gender, ml FROM obf_products")}
        self.assertEqual(rows["4006381333931"][1:], ("Creed", "Aventus", "edp", "", 100.0))
        self.assertEqual(rows["0012345678905"][1:], ("Dior", "Sauvage", "edt", "m", 100.0))
        self.assertGreater(obf.last_import(con), 0)

    def test_reimport_replaces(self):
        con = db()
        obf.run(con, opener=export(LINES))
        obf.run(con, opener=export(LINES[:1]))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM obf_products").fetchone()[0], 1)

    def test_format_change_is_an_error_not_an_empty_table(self):
        con = db()
        obf.run(con, opener=export(LINES))
        with self.assertRaises(RuntimeError):
            obf.run(con, opener=export([{"code": "1", "something": "else"}]))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM obf_products").fetchone()[0], 2)   # kept

    def test_tags_as_they_occur_in_the_real_export(self):
        def p(*tags):
            return obf.product({"code": "4006381333931", "product_name": "X", "brands": "Y", "categories_tags": list(tags)})
        # perfume tags in other languages / not normalised (counts from the 2026-11-24 export)
        self.assertEqual(p("nl:Herenparfum")["gender"], "m")
        self.assertEqual(p("nl:Damesparfum")["gender"], "f")
        self.assertEqual(p("en:Women's perfumes")["gender"], "f")
        self.assertEqual(p("en:Men's fragrances")["gender"], "m")
        self.assertEqual(p("nl:Unisex parfum")["gender"], "u")
        self.assertEqual(p("en:perfumes", "en:men-perfumes", "en:women-perfumes")["gender"], "u")
        self.assertEqual(p("en:Eau de parfum")["conc"], "edp")
        self.assertEqual(p("de:eau-de-parfum")["conc"], "edp")
        self.assertEqual(p("nl:Parfum")["gender"], "")
        # look-alikes that are not perfume
        for tag in ("de:toilettenpapier", "fr:lait-de-toilette", "fr:shampooings-aux-extraits-naturels",
                    "fr:gels-pour-la-toilette-intime", "en:perfume-free"):
            self.assertIsNone(p(tag), tag)

    def test_brand_and_name_as_in_the_real_export(self):
        r = obf.product({"code": "4006381333931", "product_name": "Giorgio Armani Acqua di Giò Pour Homme",
                         "brands": "L'Oréal,Giorgio Armani", "categories_tags": ["en:perfumes"]})
        self.assertEqual((r["brand"], r["name"]), ("Giorgio Armani", "Acqua di Giò Pour Homme"))
        r = obf.product({"code": "0737052596914", "product_name": "Hugo Boss RED", "brands": "Hugo Boss",
                         "quantity": "75 ml", "categories_tags": ["en:perfumes", "en:eau-de-toilette"]})
        self.assertEqual((r["brand"], r["name"], r["conc"]), ("Hugo Boss", "RED", "edt"))

    def test_not_perfume(self):
        for brand, name in [("Victoria's Secret", "Romantic Body Mist"), ("Rexona", "Desodorante Antitranspirante Aerosol"),
                            ("touareg", "Touareg déodorant"), ("Ucla", "Champion Glow Parfümlü Vücut ve Saç Spreyi"),
                            ("Revlon", "Charlie Blue Perfumed Body"), ("Clean", "Pure Soap"), ("Yves Rocher", "Brume Parfumée"),
                            ("AXE", "Aftershave Black"), ("Zwitsal", "Original Bodymist"), ("Sezgin Sayar", "Limon Kolonyası"),
                            ("Van Gils", "Strictly For Men - Hair & Body Wash"), ("Nivea", "Douchecrème"),
                            ("Rituals", "Body Cream"), ("Kérastase", "Shampoo")]:
            self.assertTrue(obf.not_perfume(brand, name), name)
        for brand, name in [("Burberry", "Body"), ("Armani", "Stronger With You"), ("Dior", "Sauvage"),
                            ("Chanel", "Coco Mademoiselle"), ("Lancôme", "La Vie est Belle")]:
            self.assertFalse(obf.not_perfume(brand, name), name)
        r = obf.product({"code": "4006381333931", "product_name": "Romantic Body Mist", "brands": "Victoria's Secret",
                         "categories_tags": ["en:perfumes"]})
        self.assertIsNone(r)
        r = obf.product({"code": "3614272225695", "product_name": "La Vie Est Belle Kadın Parfüm", "brands": "Lancôme",
                         "categories_tags": ["en:perfumes"]})
        self.assertEqual(r["name"], "La Vie Est Belle")

    def test_ml(self):
        self.assertEqual([obf.ml_of(q) for q in ["50 ml", "1,7 fl. oz", "10 cl", "", "100g"]], [50, 50, 100, None, None])


class Retry(unittest.TestCase):
    """obf_loop downloads only when obf.due(): a week after a good import, a day after a failed one."""
    WEEK, DAY = 7 * 86400, obf.RETRY_AFTER

    def failing(self, req, timeout=None):
        raise OSError("network down")

    def test_first_time_is_due(self):
        self.assertTrue(obf.due(db(), self.WEEK))

    def test_good_import_waits_a_week(self):
        con = db()
        obf.run(con, opener=export(LINES))
        t = obf.last_import(con)
        self.assertAlmostEqual(obf.meta(con, "attempted"), t, delta=1)
        self.assertFalse(obf.due(con, self.WEEK, t + self.WEEK - 60))
        self.assertTrue(obf.due(con, self.WEEK, t + self.WEEK))

    def test_network_error_waits_a_day(self):
        con = db()
        with self.assertRaises(OSError):
            obf.run(con, opener=self.failing)
        failed = obf.meta(con, "failed")
        self.assertGreater(failed, 0)
        self.assertAlmostEqual(obf.meta(con, "attempted"), failed, delta=1)
        self.assertFalse(obf.due(con, self.WEEK, failed + 3600))   # not every hour
        self.assertTrue(obf.due(con, self.WEEK, failed + self.DAY))

    def test_export_without_perfumes_waits_a_day(self):
        con = db()
        obf.run(con, opener=export(LINES))
        con.execute("UPDATE obf_meta SET v='1000' WHERE k='imported'")   # long ago, so a new import is due
        with self.assertRaises(RuntimeError):
            obf.run(con, opener=export([{"code": "1", "something": "else"}]))
        failed = obf.meta(con, "failed")
        self.assertEqual(obf.last_import(con), 1000)                     # the failure isn't an import
        self.assertFalse(obf.due(con, self.WEEK, failed + 3600))
        self.assertTrue(obf.due(con, self.WEEK, failed + self.DAY))

    def test_good_import_after_a_failure_counts_again(self):
        con = db()
        with self.assertRaises(OSError):
            obf.run(con, opener=self.failing)
        con.execute("UPDATE obf_meta SET v=v-1 WHERE k='failed'")       # the failure came first
        obf.run(con, opener=export(LINES))
        t = obf.last_import(con)
        self.assertFalse(obf.due(con, self.WEEK, t + self.DAY))
        self.assertTrue(obf.due(con, self.WEEK, t + self.WEEK))


class InCatalog(unittest.TestCase):
    def test_joins_shop_facts_by_barcode_and_credits_the_source(self):
        con = db()
        obf.run(con, opener=export(LINES))
        add(con, "douglas.nl", "Creed", "Aventus", "edp", top=["Pineapple"], gtins=["4006381333931"])
        self.assertEqual(catalog.build(con), 2)   # Aventus (shop + OBF together) and Sauvage
        p = catalog.perfume(con, catalog.search(con, "aventus")[0]["id"])
        self.assertEqual(p["shops"], 2)
        self.assertIn(obf.SOURCE, p["shopList"])
        self.assertEqual(p["attribution"], obf.ATTRIBUTION)
        st = catalog.stats(con)
        self.assertEqual((st["perfumes"], st["fromOpenBeautyFacts"]), (2, 2))
        self.assertIn("Open Beauty Facts", st["attribution"])

    def test_shop_spelling_wins_over_obf(self):
        con = db()
        con.execute("INSERT INTO obf_products VALUES (?,?,?,?,?,?,?,?)",
                    ("0737052074443", "Hugo Boss", "Bottled", "edt", "m", 100, "en", 0))
        add(con, "douglas.nl", "Hugo Boss", "Boss Bottled", "edt", gtins=["0737052074443"])
        catalog.build(con)
        self.assertEqual(catalog.search(con, "bottled")[0]["name"], "Boss Bottled")

    def test_no_attribution_without_obf(self):
        con = db()
        add(con, "douglas.nl", "Creed", "Aventus")
        catalog.build(con)
        self.assertNotIn("attribution", catalog.perfume(con, catalog.search(con, "aventus")[0]["id"]))


if __name__ == "__main__":
    unittest.main()
