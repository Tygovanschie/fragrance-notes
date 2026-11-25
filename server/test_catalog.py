"""Tests for the open perfume database (catalog.py). Run: python test_catalog.py"""
import json
import sqlite3
import unittest

import catalog


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE facts (
        install TEXT NOT NULL, day TEXT NOT NULL, shop TEXT NOT NULL, perfume_id INTEGER,
        brand TEXT NOT NULL, name TEXT NOT NULL, conc TEXT NOT NULL DEFAULT '', gender TEXT NOT NULL DEFAULT '', lang TEXT,
        sizes TEXT NOT NULL, gtins TEXT NOT NULL, notes TEXT NOT NULL, families TEXT NOT NULL,
        PRIMARY KEY (install, shop, brand, name, conc, gender, day))""")
    catalog.init(con)
    return con


def add(con, shop, brand, name, conc="edp", gender=None, top=(), heart=(), base=(), gtins=(), sizes=(50, 100),
        families=(), install="a", pid=None, day="2026-11-24", lang="nl"):
    con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (install, day, shop, pid, brand, name, conc, gender or '', lang, json.dumps(list(sizes)), json.dumps(list(gtins)),
                 json.dumps({"top": list(top), "heart": list(heart), "base": list(base)}), json.dumps(list(families))))


class Keys(unittest.TestCase):
    def test_brand_spellings(self):
        for a, b in [("Yves Saint Laurent", "YSL"), ("Christian Dior", "Dior"), ("Giorgio Armani", "Armani"),
                     ("Emporio Armani", "ARMANI"), ("Paco Rabanne", "Rabanne"), ("Lancôme", "Lancome"),
                     ("Jean Paul Gaultier", "Jean-Paul Gaultier"), ("Parfums de Marly", "Parfums de Marly")]:
            self.assertEqual(catalog.brand_key(a), catalog.brand_key(b), (a, b))
        self.assertNotEqual(catalog.brand_key("Gucci"), catalog.brand_key("Prada"))

    def test_names_without_brand_words(self):
        bk = catalog.brand_key("Armani")
        self.assertEqual(catalog.name_key("Emporio Armani Stronger With You Absolutely", bk),
                         catalog.name_key("Stronger With You Absolutely", bk))
        self.assertEqual(catalog.name_key("N°5", "chanel"), catalog.name_key("No. 5", "chanel"))
        self.assertEqual(catalog.name_key("Guilty Pour Homme", "gucci"), catalog.name_key("Gucci Guilty for Men", "gucci"))
        self.assertNotEqual(catalog.name_key("Guilty Pour Homme", "gucci"), catalog.name_key("Guilty", "gucci"))

    def test_pick_brand(self):
        name = "Giorgio Armani Acqua di Giò Pour Homme"
        self.assertEqual(catalog.pick_brand(["L'Oréal", " Giorgio Armani"], name), "Giorgio Armani")
        self.assertEqual(catalog.pick_brand(["L'Oréal", "Armani"], name), "Armani")       # via the alias
        self.assertEqual(catalog.pick_brand(["L'Oréal", "Lancôme"], "La Vie est Belle"), "Lancôme")  # known house
        self.assertEqual(catalog.pick_brand(["Creed", "Other"], "Aventus"), "Creed")      # else the first
        self.assertEqual(catalog.pick_brand(["", " "], "X"), "")

    def test_strip_brand(self):
        self.assertEqual(catalog.strip_brand("Hugo Boss RED", "Hugo Boss"), "RED")
        self.assertEqual(catalog.strip_brand("Chanel - Chance Eau Tendre", "Chanel"), "Chance Eau Tendre")
        self.assertEqual(catalog.strip_brand("Lancôme La Vie est Belle", "Lancome"), "La Vie est Belle")
        self.assertEqual(catalog.strip_brand("Coco Chanel", "Chanel"), "Coco Chanel")      # not in front
        self.assertEqual(catalog.strip_brand("Boss Woman", "Hugo Boss"), "Boss Woman")     # not the brand as written
        self.assertEqual(catalog.strip_brand("Gucci Pour Homme", "Gucci"), "Gucci Pour Homme")  # nothing real left
        self.assertEqual(catalog.strip_brand("Chanel", "Chanel"), "Chanel")
        for name, brand in [("WhatsApp Perfume", "WhatsApp"), ("Touareg déodorant", "Touareg"),
                            ("Denver Deodorant Body", "Denver")]:               # only a product word left
            self.assertEqual(catalog.strip_brand(name, brand), name)
        self.assertEqual(catalog.strip_brand("Diorissimo", "Dior"), "Diorissimo")         # whole words only

    def test_note_keys(self):
        self.assertEqual(catalog.note_key("Rum Akkoord"), catalog.note_key("rum"))
        self.assertEqual(catalog.note_key("Crème brûlée"), "creme brulee")

    def test_notes_across_shops_and_languages(self):
        same = [("Kastanjes", "Kastanje", "Chestnut", "Châtaigne"), ("Vanille", "Vanilla", "Vainilla"),
                ("Tonkaboon", "Tonka Bean", "Fève Tonka"), ("Roze Peper", "Pink Pepper", "Baies roses"),
                ("compositie van zure kersen", "Zure kersen", "Sour cherry"), ("Jenever", "Jeneverbes", "Juniper"),
                ("Kruidig", "specerijen", "Spicy"), ("Oriëntaalse", "Oriental"), ("Houtachtig", "Woody"),
                ("Maracuja", "Passion fruit")]
        for group in same:
            self.assertEqual({catalog.note_key(n) for n in group}, {catalog.note_key(group[0])}, group)
        # Not the same note: glazed chestnut, pepper vs pink pepper, a word that isn't in the table.
        self.assertNotEqual(catalog.note_key("Geglazuurde kastanje"), catalog.note_key("Kastanje"))
        self.assertNotEqual(catalog.note_key("Peper"), catalog.note_key("Roze Peper"))
        self.assertEqual(catalog.note_key("Belambra Hout"), "belambra hout")

    def test_display_name(self):
        self.assertEqual(catalog.display_name("STRONGER WITH YOU MANNEN"), "STRONGER WITH YOU")
        self.assertEqual(catalog.display_name("Power of You voor Vrouwen"), "Power of You")
        self.assertEqual(catalog.display_name("Guilty Pour Homme"), "Guilty Pour Homme")   # part of the name
        self.assertEqual(catalog.display_name("Mannen"), "Mannen")
        self.assertTrue(catalog.shouting("STRONGER WITH YOU"))
        self.assertFalse(catalog.shouting("Stronger With You"))
        self.assertFalse(catalog.shouting("CK"))


class Build(unittest.TestCase):
    def test_same_perfume_from_several_shops(self):
        con = db()
        add(con, "douglas.nl", "Armani", "Emporio Armani Stronger With You Absolutely", "parfum", "m",
            top=["Rum", "Bergamot"], heart=["Ceder", "Davana"], base=["Lavendel", "Cederhout"], families=["Houtachtig"])
        add(con, "notino.nl", "Giorgio Armani", "Stronger With You Absolutely", "parfum", None,
            top=["Rum"], heart=["Davana"], base=["Vanille"], install="b")
        add(con, "douglas.nl", "Armani", "Emporio Armani Stronger With You Absolutely", "parfum", "m",
            top=["Rum", "Bergamot"], install="c")   # same shop again: no extra confirmation
        self.assertEqual(catalog.build(con), 1)
        p = catalog.search(con, "stronger absolutely")[0]
        self.assertEqual((p["name"], p["conc"], p["shops"]), ("Stronger With You Absolutely", "parfum", 2))
        full = catalog.perfume(con, p["id"])
        top = {n["name"]: n for n in full["notes"]["top"]}
        self.assertTrue(top["Rum"]["confirmed"])
        self.assertFalse(top["Bergamot"]["confirmed"])          # only Douglas says so
        self.assertEqual(full["reports"], 3)
        self.assertEqual(full["license"], "ODbL-1.0")

    def test_versions_stay_apart(self):
        con = db()
        add(con, "douglas.nl", "Dior", "Sauvage", "edt")
        add(con, "douglas.nl", "Dior", "Sauvage", "parfum")
        add(con, "douglas.nl", "Dior", "Sauvage Elixir", "parfum")
        add(con, "notino.nl", "Gucci", "Guilty", "edp", "m", install="b")
        add(con, "notino.nl", "Gucci", "Guilty", "edp", "f", install="b")
        self.assertEqual(catalog.build(con), 5)

    def test_unknown_gender_joins_the_only_version(self):
        con = db()
        add(con, "douglas.nl", "Gucci", "Guilty Pour Homme", "edp", "m")
        add(con, "notino.nl", "Gucci", "Gucci Guilty Pour Homme", "edp", None, install="b")
        self.assertEqual(catalog.build(con), 1)

    def test_unknown_conc_joins_the_only_one(self):
        con = db()
        add(con, "openbeautyfacts.org", "Chanel", "Coco Mademoiselle", "", "f")
        add(con, "douglas.nl", "Chanel", "Coco Mademoiselle", "edp", "f", install="b")
        self.assertEqual(catalog.build(con), 1)
        self.assertEqual(catalog.search(con, "coco mademoiselle")[0]["conc"], "edp")
        con.execute("DELETE FROM facts")
        add(con, "openbeautyfacts.org", "Dior", "Sauvage", "")
        add(con, "douglas.nl", "Dior", "Sauvage", "edt", install="b")
        add(con, "notino.nl", "Dior", "Sauvage", "parfum", install="c")
        self.assertEqual(catalog.build(con), 3)

    def test_gender_word_at_the_end_is_the_gender(self):
        # As sent on 2026-11-24: ICI Paris XL adds "Mannen", Douglas doesn't; no shared barcode.
        con = db()
        add(con, "douglas.nl", "Armani", "Emporio Armani Stronger With You", "edt", "m", base=["Kastanjes", "Vanille"])
        add(con, "iciparisxl.nl", "ARMANI", "STRONGER WITH YOU MANNEN", "edt", "m",
            base=["Geglazuurde kastanje", "Vanille"], install="b")
        self.assertEqual(catalog.build(con), 1)
        p = catalog.search(con, "stronger with you")[0]
        self.assertEqual((p["gender"], p["shops"], p["confirmedNotes"]), ("m", 2, 1))   # Vanille, from 2 shops
        # A gender word in the name also gives the gender when the shop doesn't.
        con.execute("DELETE FROM facts")
        add(con, "douglas.nl", "Gucci", "Guilty Pour Homme", "edp", None)
        add(con, "notino.nl", "Gucci", "Guilty", "edp", "f", install="b")
        add(con, "notino.nl", "Dior", "Dior Homme", "edt", None, install="b")         # the name is only that word
        self.assertEqual(catalog.build(con), 3)
        self.assertEqual(sorted((p["name"], p["gender"]) for p in catalog.search(con, "guilty")),
                         [("Guilty", "f"), ("Guilty Pour Homme", "m")])
        self.assertEqual(catalog.search(con, "dior homme")[0]["name"], "Dior Homme")

    def test_ids_stay_when_the_gender_word_moves(self):
        # Before this rule the key had the gender word in the name; that perfume must keep its id.
        con = db()
        add(con, "douglas.nl", "Gucci", "Guilty Pour Homme", "edp", "m")
        con.execute("INSERT INTO catalog_keys VALUES ('gucci|guilty homme|edp|m', 'abcdef123456')")
        catalog.build(con)
        self.assertEqual(catalog.search(con, "guilty")[0]["id"], "abcdef123456")

    def test_notes_confirmed_across_languages(self):
        con = db()
        add(con, "douglas.nl", "Armani", "Stronger With You", "edt", "m", base=["Kastanjes", "Vanille"], families=["Kruidig"])
        add(con, "notino.de", "Armani", "Stronger With You", "edt", "m", base=["Kastanie", "Vanille"],
            families=["würzig"], install="b", lang="de")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "stronger")[0]["id"])
        self.assertEqual({(n["key"], n["confirmed"]) for n in p["notes"]["base"]}, {("chestnut", True), ("vanilla", True)})
        self.assertEqual([(f["key"], f["shops"]) for f in p["families"]], [("spicy", 2)])
        self.assertEqual(p["confirmedNotes"], 2)
        self.assertEqual(p["review"], [])   # the notes no longer look different

    def test_clean_display_names(self):
        con = db()
        add(con, "douglas.nl", "Armani", "Emporio Armani Stronger With You", "edt", "m")
        add(con, "iciparisxl.nl", "ARMANI", "STRONGER WITH YOU MANNEN", "edt", "m", install="b")
        add(con, "zalando.nl", "Armani Beauty", "Acqua di Giò", "edt", "m", install="c")
        add(con, "notino.nl", "hugo boss", "Boss Bottled", "edt", "m", install="d")
        add(con, "douglas.nl", "Hugo Boss", "Boss The Scent", "edt", "m", install="e")
        add(con, "notino.nl", "Hugo Boss", "Boss Alive", "edp", "f", install="e")
        catalog.build(con)
        p = catalog.search(con, "stronger with you")[0]
        self.assertEqual((p["brand"], p["name"]), ("Armani", "Emporio Armani Stronger With You"))
        self.assertEqual(catalog.search(con, "acqua")[0]["brand"], "Armani")             # one spelling per house
        self.assertEqual(catalog.search(con, "bottled")[0]["brand"], "Hugo Boss")        # not "hugo boss"
        self.assertEqual(catalog.search(con, "armani beauty acqua")[0]["name"], "Acqua di Giò")   # old spellings still found
        self.assertEqual(len(catalog.search(con, "mannen")), 1)

    def test_lookup(self):
        con = db()
        add(con, "douglas.nl", "Gucci", "Guilty Pour Homme", "edp", "m", gtins=["8005610298764"])
        add(con, "douglas.nl", "Gucci", "Guilty", "edp", "f", install="b")
        add(con, "notino.nl", "Armani", "Stronger With You", "edt", "m", install="c")
        catalog.build(con)
        name = lambda p: p and p["name"]
        self.assertEqual(name(catalog.lookup(con, gtins=["8005610298764"])), "Guilty Pour Homme")
        # Same name, men's and women's version: the shop's gender (or the name) decides; unknown is no match.
        self.assertEqual(name(catalog.lookup(con, brand="Gucci", name="Guilty", conc="edp", gender="f")), "Guilty")
        self.assertEqual(name(catalog.lookup(con, brand="GUCCI", name="Gucci Guilty voor Mannen", conc="edp")), "Guilty Pour Homme")
        self.assertIsNone(catalog.lookup(con, brand="Gucci", name="Guilty", conc="edp"))
        # Another shop's spelling and no concentration on the page.
        self.assertEqual(name(catalog.lookup(con, brand="Giorgio Armani", name="Emporio Armani Stronger With You")), "Stronger With You")
        self.assertIsNone(catalog.lookup(con, brand="Armani", name="Stronger With You", conc="parfum", gender="m"))
        self.assertIsNone(catalog.lookup(con, brand="", name="", gtins=["123", "x"]))

    def test_armani_spellings(self):
        con = db()
        add(con, "zalando.nl", "Armani Beauty", "EA STRONGER WITH YOU INTENSELY", "edp")
        add(con, "notino.nl", "Armani", "Emporio Stronger With You Intensely", "edp", install="b")
        self.assertEqual(catalog.build(con), 1)

    def test_same_barcode_joins_different_names(self):
        con = db()
        add(con, "douglas.nl", "Lancôme", "La Vie est Belle", gtins=["3605532612768"])
        add(con, "sephora.nl", "Lancome", "La vie est belle L'Eau de Parfum", gtins=["3605532612768"], install="b")
        self.assertEqual(catalog.build(con), 1)

    def test_review_flags(self):
        con = db()
        add(con, "douglas.nl", "Creed", "Aventus", top=["Pineapple"], pid=9828)
        add(con, "notino.nl", "Creed", "Aventus", top=["Lemon"], pid=1234, install="b")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "aventus")[0]["id"])
        self.assertIn("several Fragrantica matches", p["review"])
        self.assertIn("shops list different notes", p["review"])
        self.assertEqual(catalog.stats(con)["toReview"], 1)

    def test_ids_stay_when_spelling_shifts(self):
        con = db()
        add(con, "douglas.nl", "Creed", "Aventus", gtins=["4006381333931"])
        catalog.build(con)
        first = catalog.search(con, "aventus")[0]["id"]
        # More shops arrive with a different spelling of the name (same barcode), so that becomes the
        # most common key; the id must not change.
        for i, shop in enumerate(["notino.nl", "sephora.nl", "ici.nl"]):
            add(con, shop, "Creed", "Aventus for Men", gtins=["4006381333931"], install=str(i))
        catalog.build(con)
        self.assertEqual([p["id"] for p in catalog.search(con, "aventus")], [first])
        self.assertIsNotNone(catalog.perfume(con, first))

    def test_gender_is_text_on_perfume_page(self):
        con = db()
        add(con, "douglas.nl", "Gucci", "Guilty Pour Homme", gender="m")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "guilty")[0]["id"])
        self.assertEqual(p["gender"], "m")
        self.assertEqual(p["genderVotes"][0]["name"], "m")

    def test_rebuild_replaces(self):
        con = db()
        add(con, "douglas.nl", "Creed", "Aventus")
        catalog.build(con)
        con.execute("DELETE FROM facts")
        self.assertEqual(catalog.build(con), 0)
        self.assertEqual(catalog.search(con, "aventus"), [])


if __name__ == "__main__":
    unittest.main()
