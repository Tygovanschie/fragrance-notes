"""Tests for the open perfume database (catalog.py). Run: python test_catalog.py"""
import json
import sqlite3
import unittest
import unittest.mock

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
        families=(), install="a", pid=None, day="2026-11-24", lang="nl", mentioned=()):
    con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (install, day, shop, pid, brand, name, conc, gender or '', lang, json.dumps(list(sizes)), json.dumps(list(gtins)),
                 json.dumps({"top": list(top), "heart": list(heart), "base": list(base), **({"mentioned": list(mentioned)} if mentioned else {})}),
                 json.dumps(list(families))))


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
        self.assertEqual(catalog.note_key("Maanstof Hout"), "maanstof hout")
        self.assertEqual(catalog.note_key("Belambra Hout"), "belambre")    # Givaudan's woody amber, as shops misspell it

    def test_display_name(self):
        self.assertEqual(catalog.display_name("STRONGER WITH YOU MANNEN"), "STRONGER WITH YOU")
        self.assertEqual(catalog.display_name("Power of You voor Vrouwen"), "Power of You")
        self.assertEqual(catalog.display_name("Olfactories - Compulsion - Neutral", "prada"), "Olfactories Compulsion")   # prada.com colour option
        self.assertEqual(catalog.display_name("Luna Rossa Carbon - ( )", "prada"), "Luna Rossa Carbon")
        self.assertEqual(catalog.display_name("Paradigme - Le Parfum ( )", "prada"), "Paradigme Le Parfum")
        self.assertEqual(catalog.display_name("Neutral Ground"), "Neutral Ground")                                # only a tail after a dash
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
        self.assertEqual((p["gender"], p["shops"], p["confirmedNotes"]), ("m", 2, 2))   # Vanille, and Kastanjes + Geglazuurde kastanje = glazed chestnut
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

    def test_promotion_words_dont_split_a_perfume(self):
        con = db()
        add(con, "douglas.nl", "Armani", "Emporio Stronger With You Intensely", top=["Roze peper"])
        catalog.build(con)
        first = catalog.search(con, "intensely")[0]["id"]
        add(con, "parfumerie.nl", "Armani", "Stronger With You Intensely - Summer Deal", top=["Roze peper"], install="b")
        add(con, "zalando.nl", "Armani Beauty", "EA STRONGER WITH YOU INTENSELY", install="c")
        add(con, "deloox.nl", "Armani", "Giorgio Stronger With You Intensely (Travel)", install="d")
        catalog.build(con)
        found = catalog.search(con, "intensely")
        self.assertEqual([p["id"] for p in found], [first])
        self.assertEqual(found[0]["name"], "Stronger With You Intensely")
        self.assertEqual(found[0]["confirmedNotes"], 1)
        for raw, clean in [("YSL Libre - Rechargeable", "YSL Libre"), ("Acqua di Giò Pour Homme Refillable", "Acqua di Giò Pour Homme"),
                           ("Angel recharge", "Angel"), ("Tester", "Tester"), ("Club De Nuit Intense Man New in Box", "Club De Nuit Intense Man"),
                           ("Libre Refillable - Summer Deal", "Libre"), ("Sunset", "Sunset"), ("Jet Set", "Jet Set")]:
            self.assertEqual(catalog.strip_promo(raw), clean, raw)

    def test_shop_words_and_collection_names_tygo_picked(self):
        # From the maintenance email of 2026-11-26: VERSTUIVER and "kopen" are shop words, "Signature Fragrances"
        # a Tom Ford collection label, "J.P. Gaultier" the house; "Absolutely" is part of the name.
        for raw, clean in [("ALLURE HOMME SPORT VERSTUIVER", "ALLURE HOMME SPORT"), ("I (1) - kopen", "I (1)"),
                           ("Stronger With You Absolutely", "Stronger With You Absolutely")]:
            self.assertEqual(catalog.strip_promo(raw), clean, raw)
        self.assertEqual(catalog.display_name("Signature Fragrances Ombré Leather", "tom ford"), "Ombré Leather")
        self.assertEqual(catalog.name_key("Signature Fragrances Ombré Leather", "tom ford"), catalog.name_key("Ombré Leather", "tom ford"))
        self.assertEqual(catalog.name_key("J.P. Gaultier Le Male", catalog.brand_key("Jean Paul Gaultier")), "le male")
        self.assertEqual(catalog.display_name("Private Blend", "tom ford"), "Private Blend")   # nothing left: unchanged
        for spelling, note in [("Rode Peper", "chili pepper"), ("Permento Bes", "allspice"), ("Bes", "berries"),
                               ("Exclusief Kaneellikeur Akkoord", "cinnamon liqueur"), ("Amberever", "amberever")]:
            self.assertEqual(catalog.NOTE_CANON.get(catalog.note_key(spelling)), note, spelling)

    def test_house_words_in_front_of_the_name(self):
        for name, brand, shown in [("Emporio Stronger With You", "armani", "Stronger With You"),
                                   ("Giorgio Stronger With You", "armani", "Stronger With You"),
                                   ("EA STRONGER WITH YOU INTENSELY", "armani", "STRONGER WITH YOU INTENSELY"),
                                   ("Armani Privé Cuir Améthyste", "armani", "Armani Privé Cuir Améthyste"),
                                   ("Emporio Armani Stronger With You", "armani", "Emporio Armani Stronger With You"),
                                   ("Armani Code", "armani", "Armani Code"),
                                   ("Narciso Poudrée", "narciso rodriguez", "Narciso Poudrée"),
                                   ("Cerruti 1881 Black", "cerruti 1881", "Cerruti 1881 Black"),
                                   ("Emporio Homme", "armani", "Emporio Homme"),               # nothing real left
                                   ("Emporio Armani", "armani", "Emporio Armani"),
                                   ("Aventus", "creed", "Aventus")]:
            self.assertEqual(catalog.display_name(name, brand), shown, name)

    def test_note_dictionary_is_unambiguous(self):
        seen = {}
        for line in catalog.NOTE_WORDS.strip().splitlines():
            canon, variants = line.split(":", 1)
            for v in (x.strip() for x in variants.split("|")):
                if v:
                    self.assertEqual(seen.get(v, canon), canon, f"{v!r} is in both {seen.get(v)!r} and {canon!r}")
                    seen[v] = canon
        self.assertEqual(set(catalog.NOTE_PARENTS) - catalog.NOTE_EN, set())
        self.assertEqual(set(catalog.NOTE_PARENTS.values()) - catalog.NOTE_EN, set())
        self.assertEqual(set(catalog.USUAL_TIER) - catalog.NOTE_EN, set())
        self.assertEqual(catalog.usual_tier("oakmoss"), "base")    # its main accord is green, but it is a base note

    def test_note_names_shops_use(self):
        for raw, key in [("Tuberoos (Nachthyacint)", "tuberose"), ("Indiase Patchouli", "patchouli"),
                         ("Transparant Frangipani Akkoord", "frangipani"), ("Tonka Boon", "tonka bean"),
                         ("Oranje Bloesem", "orange blossom"), ("Mariene Notities", "marine"), ("Benzoine", "benzoin"),
                         ("Bloed mandarijn", "blood mandarin"), ("Italiaanse Bergamot", "bergamot"),
                         ("Vioolblaadjes", "violet leaf"), ("Zachte Muskus", "musk"), ("Witte Musk", "white musk"),
                         ("Monoi-olie", "monoi"), ("Iris", "iris"), ("Pruim", "plum"), ("Anjer", "carnation"),
                         ("Ambroxan", "ambroxan"), ("Ozonische Noten", "ozonic"), ("Kruidige geurnoten", "spicy")]:
            self.assertEqual(catalog.note_key(raw), key, raw)
        for junk in ("Bovenlichaam", "Noot", "Geurnoten", ""):
            self.assertEqual(catalog.note_key(junk), "", junk)

    def test_each_note_once(self):
        con = db()
        add(con, "douglas.nl", "Dior", "Sauvage", "edp", top=["Bergamot", "Peper"], heart=["Vanille", "Lavendel"],
            base=["Ambroxan"])
        add(con, "notino.nl", "Dior", "Sauvage", "edp", top=["Roze Peper"], heart=["Lavendel"], base=["Bergamot", "Vanille"],
            install="b")
        add(con, "deloox.nl", "Dior", "Sauvage", "edp", base=["Vanille", "Ambroxan (Ambrox)"], install="c")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "sauvage")[0]["id"])
        where = {n["key"]: (t, n["shops"], n["confirmed"]) for t in ("top", "heart", "base") for n in p["notes"][t]}
        self.assertEqual(len(where), sum(len(p["notes"][t]) for t in ("top", "heart", "base")))   # no note twice
        self.assertEqual(where["pink pepper"], ("top", 2, True))       # "Peper" + "Roze Peper": one note, both shops
        self.assertNotIn("pepper", where)
        self.assertEqual(where["vanilla"], ("base", 3, True))          # 2 shops say base, 1 heart
        self.assertEqual(where["bergamot"], ("top", 2, True))          # 1 top, 1 base: where it usually sits
        self.assertEqual(where["ambroxan"], ("base", 2, True))
        # Two precise forms: the general one stays on its own.
        con = db()
        add(con, "douglas.nl", "X", "Y", top=["Peper", "Roze peper"])
        add(con, "notino.nl", "X", "Y", top=["Zwarte peper"], install="b")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "y")[0]["id"])
        self.assertEqual(sorted(n["key"] for n in p["notes"]["top"]), ["black pepper", "pepper", "pink pepper"])

    def test_name_most_shops_use(self):
        con = db()
        for i, (shop, brand, name) in enumerate([("deloox.nl", "Hugo Boss", "Boss Bottled"), ("douglas.nl", "Hugo Boss", "Boss Bottled"),
                                                 ("douglas.nl", "Hugo Boss", "Boss Bottled"), ("iciparisxl.nl", "HUGO BOSS", "BOTTLED"),
                                                 ("kruidvat.nl", "Hugo Boss", "Bottled")]):
            add(con, shop, brand, name, "edt", install=str(i))
        catalog.build(con)
        self.assertEqual(catalog.search(con, "bottled")[0]["name"], "Boss Bottled")

    def test_one_word_name_with_the_house_after_it(self):
        con = db()
        add(con, "dior.com", "DIOR", "Miss", "edp", "f")                       # the brand site leaves "Dior" out
        add(con, "douglas.nl", "DIOR", "Miss Dior", "edp", "f", install="b")
        add(con, "dior.com", "DIOR", "Sauvage", "edt", "m", install="c")
        add(con, "notino.nl", "Dior", "Dior Sauvage", "edt", "m", install="d")
        catalog.build(con)
        self.assertEqual(catalog.search(con, "miss")[0]["name"], "Miss Dior")
        self.assertEqual(catalog.search(con, "sauvage")[0]["name"], "Sauvage")   # the house in front is no name

    def test_deodorant_is_not_the_perfume(self):
        con = db()
        add(con, "deloox.nl", "Hugo Boss", "Boss Bottled", "edt", top=["Appel"])
        add(con, "deloox.nl", "Hugo Boss", "Boss Bottled Deodorant", "", install="b")
        add(con, "douglas.nl", "Hugo Boss", "Boss Bottled Shower Gel", "", install="c")
        catalog.build(con)
        self.assertEqual([p["name"] for p in catalog.search(con, "bottled")], ["Boss Bottled"])

    def test_new_note_words(self):
        self.assertEqual(catalog.note_key("Geglazuurde kastanje"), "glazed chestnut")
        self.assertEqual(catalog.note_key("Bourbon Vanille"), "bourbon vanilla")
        self.assertEqual(catalog.note_key("Kastanje"), "chestnut")
        self.assertEqual(catalog.note_key("Frangipani"), "frangipani")

    def test_brand_site_notes_are_official(self):
        con = db()
        # armani.com only tells its story: chestnut, vanilla, leather, no tiers. Douglas has a pyramid with one of them.
        add(con, "armani.com", "Emporio Armani", "Stronger With You Intensely", mentioned=["The", "Chestnut", "Vanilla", "Leather", "Room"])
        add(con, "douglas.nl", "Armani", "Stronger With You Intensely", top=["Roze peper"], base=["Vanille", "Iris"], install="b")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "intensely")[0]["id"])
        where = {n["key"]: (t, n["confirmed"], n.get("official")) for t in ("top", "heart", "base") for n in p["notes"][t]}
        self.assertEqual(where["vanilla"], ("base", True, "armani.com"))       # Douglas's tier, confirmed by the brand
        self.assertEqual(where["chestnut"], (catalog.usual_tier("chestnut"), True, "armani.com"))   # only mentioned: where it usually sits
        self.assertTrue(where["leather"][1])
        self.assertEqual(where["iris"], ("base", False, None))                 # one shop, not the brand: not confirmed
        self.assertEqual(where["pink pepper"][1:], (False, None))
        self.assertNotIn("tea", where)                                          # "The" in a story is not thé
        self.assertNotIn("cream", where)
        # The brand's own pyramid decides the tier, and its notes need no second shop.
        con = db()
        add(con, "jeanpaulgaultier.com", "Jean Paul Gaultier", "Le Male", "edt", top=["Lavande"], heart=["Menthe"], base=["Vanille"])
        add(con, "douglas.nl", "Jean Paul Gaultier", "Le Male", "edt", top=["Munt"], install="b")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "le male")[0]["id"])
        where = {n["key"]: (t, n["confirmed"]) for t in ("top", "heart", "base") for n in p["notes"][t]}
        self.assertEqual(where, {"lavender": ("top", True), "mint": ("heart", True), "vanilla": ("base", True)})
        # Another house's site, or "mentioned" from a normal shop, confirms nothing.
        con = db()
        add(con, "armani.com", "Dior", "Sauvage", mentioned=["Bergamot", "Ambroxan"])
        add(con, "douglas.nl", "Dior", "Sauvage", top=["Bergamot"], mentioned=["Pepper"], install="b")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "sauvage")[0]["id"])
        notes = {n["key"]: n["confirmed"] for t in ("top", "heart", "base") for n in p["notes"][t]}
        self.assertEqual(notes, {"bergamot": False})
        self.assertTrue(catalog.is_official("armani.com", "Giorgio Armani"))
        self.assertTrue(catalog.is_official("tomfordbeauty.com", "TOM FORD BEAUTY"))
        self.assertTrue(catalog.is_official("bykilian.com", "By Kilian"))
        self.assertTrue(catalog.is_official("maisonmargiela-fragrances.com", "Replica"))
        self.assertFalse(catalog.is_official("armani.com", "Dior"))
        self.assertFalse(catalog.is_official("douglas.nl", "Armani"))

    def test_parfumwebshop_notes(self):
        for raw, key in [("Kastanjeakkoord", "chestnut"), ("Vetiveressence", "vetiver"), ("Muntolie", "mint"),
                         ("Houtachtige Leernoten", "leather"), ("roosfacetten", "rose"), ("Ceder Hout", "cedar"),
                         ("Barnsteen", "amber"), ("Pure Roze Peper", "pink pepper"), ("Roos Absoluut", "rose"),
                         ("Echte Arabische Jasmijn", "jasmine"), ("Eiken Mos", "oakmoss"), ("Patchuli", "patchouli"),
                         ("Trio van Cederhout", "cedar"), ("Aquatische Noten", "aquatic"), ("Lavandin", "lavandin"),
                         ("Pepermunt Olie", "peppermint"), ("Sinaasappelboom bloesem", "orange blossom"),
                         ("Witte Muskus", "white musk"), ("Witte peper", "white pepper"), ("Ambrofix™", "ambroxan"),
                         ("Vanille-Absolu uit Madagaskar", "vanilla"), ("Gekristalliseerd Kastanje Akkoord", "glazed chestnut")]:
            self.assertEqual(catalog.note_key(raw), key, raw)
        self.assertEqual(catalog.note_key("Een intrigerende"), "")
        top = ["Bergamot", "Gember", "Appel Hart noten: Salie", "Jeneverbes", "Geranium Basis noten: Vetiver", "Ceder- Amberhout"]
        self.assertEqual(catalog.tier_notes(top, "top"), ["Bergamot", "Gember", "Appel"])
        self.assertEqual(catalog.tier_notes(["Vetiver", "Ceder- Amberhout"], "base"), ["Vetiver", "Ceder", "Amberhout"])
        self.assertEqual(catalog.tier_notes(["Hartnoten: Peperhout", "Iris"], "heart"), ["Peperhout", "Iris"])
        self.assertEqual(catalog.tier_notes(["Basisnoten: ceder", "Iris"], "top"), [])
        # Heart and base notes that came in under "top" stay in their own tier.
        con = db()
        add(con, "parfumwebshop.nl", "Yves Saint Laurent", "Y", "edp", top=top, heart=["Salie", "Jeneverbes", "Geranium"],
            base=["Vetiver", "Ceder- Amberhout"])
        add(con, "douglas.nl", "Yves Saint Laurent", "Y", "edp", top=["Appel", "Gember"], heart=["Salie"], base=["Amberhout"],
            install="b")
        catalog.build(con)
        p = catalog.perfume(con, catalog.search(con, "y")[0]["id"])
        where = {n["key"]: t for t in ("top", "heart", "base") for n in p["notes"][t]}
        self.assertEqual((where["sage"], where["juniper"], where["vetiver"], where["amberwood"]), ("heart", "heart", "base", "base"))
        self.assertNotIn("appel hart salie", where)

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


class Gate(unittest.TestCase):
    """gate.py: what the website shows after a rebuild."""
    NOTES = (["Bergamot", "Pepper"], ["Lavender"], ["Ambroxan"])

    def perfume(self, con, brand, name, install="a", gender="m", conc="edt"):
        top, heart, base = self.NOTES
        for shop in ("douglas.nl", "notino.nl"):
            add(con, shop, brand, name, conc, gender, top=top, heart=heart, base=base, install=install + shop)

    def setUp(self):
        import gate
        self.gate = gate
        self.con = db()
        self.perfume(self.con, "Dior", "Sauvage")
        self.perfume(self.con, "Armani", "Stronger With You", install="b")
        catalog.build(self.con)
        self.run_gate()

    def run_gate(self, now=None, fixes=None):
        return self.gate.run(self.con, now=now, fixes=fixes or {})

    def shown(self):
        return {p["id"]: p for p in self.gate.published(self.con)}

    def pid(self, name):
        return self.con.execute("SELECT id FROM catalog WHERE name=?", (name,)).fetchone()[0]

    def test_first_run_keeps_what_is_online(self):
        self.assertEqual(sorted(p["name"] for p in self.shown().values()), ["Sauvage", "Stronger With You"])
        self.assertEqual(self.gate.open_items(self.con), [])

    def test_growth_goes_through_by_itself(self):
        add(self.con, "iciparisxl.nl", "Dior", "Sauvage", "edt", "m", top=["Bergamot", "Pepper", "Elemi"], heart=["Lavender"],
            base=["Ambroxan"], install="z")
        catalog.build(self.con)
        self.run_gate()
        self.assertEqual(self.shown()[self.pid("Sauvage")]["shops"], 3)
        self.assertEqual(self.gate.open_items(self.con), [])

    def test_a_rename_is_held_until_approved(self):
        pid = self.pid("Sauvage")
        self.con.execute("UPDATE catalog SET name='Sauvage - Summer Box' WHERE id=?", (pid,))
        self.run_gate()
        self.assertEqual(self.shown()[pid]["name"], "Sauvage")                 # the page keeps its approved name
        item = self.gate.open_items(self.con)[0]
        self.assertEqual((item["id"], item["kind"]), (pid, "name"))
        self.assertTrue(self.gate.decide(self.con, pid, "name", item["value"], "approve"))
        self.assertEqual(self.shown()[pid]["name"], "Sauvage - Summer Box")
        self.assertEqual(self.gate.open_items(self.con), [])
        self.run_gate()
        self.assertEqual(self.gate.open_items(self.con), [])                   # never asked again

    def test_rejected_change_keeps_the_page_and_is_not_asked_again(self):
        pid = self.pid("Sauvage")
        self.con.execute("UPDATE catalog SET gender='f' WHERE id=?", (pid,))
        self.run_gate()
        item = self.gate.open_items(self.con)[0]
        self.assertEqual(item["kind"], "gender")
        self.gate.decide(self.con, pid, "gender", item["value"], "reject")
        self.run_gate()
        self.assertEqual(self.shown()[pid]["gender"], "m")
        self.assertEqual(self.gate.open_items(self.con), [])

    def test_new_perfumes_need_a_clean_name(self):
        self.perfume(self.con, "Prada", "Olfactories - Compulsion - ( )", install="c", gender="u", conc="edp")
        self.perfume(self.con, "Prada", "Luna Rossa Ocean", install="d")
        catalog.build(self.con)
        self.run_gate()
        names = sorted(p["name"] for p in self.shown().values())
        self.assertIn("Luna Rossa Ocean", names)
        held = self.gate.open_items(self.con)
        self.assertEqual([i["kind"] for i in held], [])  # catalog.tidy_name already cleans this title
        self.assertIn("Olfactories Compulsion", names)

    def test_new_perfume_with_a_problem_waits(self):
        self.perfume(self.con, "Hugo Boss", "BOTTLED NIGHT", install="c")
        catalog.build(self.con)
        self.run_gate()
        self.assertNotIn("BOTTLED NIGHT", [p["name"] for p in self.shown().values()])
        item = self.gate.open_items(self.con)[0]
        self.assertEqual(item["kind"], "new")
        self.assertIn("capitals", item["detail"])
        self.gate.decide(self.con, item["id"], "new", item["value"], "approve")
        self.assertIn("BOTTLED NIGHT", [p["name"] for p in self.shown().values()])

    def test_brand_site_colour_option_merges_and_keeps_the_published_id(self):
        # 2026-11-27: prada.com's "Paradigme - Neutral" (a page, official notes) and Douglas's "Paradigme" were two
        # perfumes. Now they are one, under the published id; the other id redirects and nothing waits for a person.
        add(self.con, "prada.com", "PRADA", "Paradigme - Neutral", "edp", "m", top=["Calabrian Bergamot Heart"],
            heart=["Bourbon Geranium"], base=["Ambery Woods"], install="p")
        add(self.con, "douglas.nl", "Prada", "Paradigme", "edp", "m", top=["Bergamot"], install="q")
        import pages
        orig = catalog.name_key   # the old name_key kept the colour option (here the same as promo=False)
        with unittest.mock.patch.object(catalog, "name_key", lambda n, b, promo=True: orig(n, b, promo=False)):
            catalog.build(self.con)          # the old rule: two perfumes, the brand site's one gets a page
        self.run_gate()
        ids = {r[0]: r[1] for r in self.con.execute("SELECT id, shops FROM catalog WHERE name LIKE 'Paradigme%'")}
        self.assertEqual(len(ids), 2)
        page = next(i for i in ids if i in self.shown())
        other = next(i for i in ids if i != page)
        catalog.build(self.con)
        self.assertEqual([r[0] for r in self.con.execute("SELECT id FROM catalog WHERE name='Paradigme'")], [page])
        self.assertEqual(catalog.moved_to(self.con, other), page)
        self.assertEqual(catalog.perfume(self.con, other)["id"], page)
        self.run_gate()
        self.assertEqual(self.gate.open_items(self.con), [])
        status, _, where = pages.route(self.con, f"/perfume/{other}", "", None)
        self.assertEqual((status, where.split("-")[0]), (301, f"/perfume/{page}"))
        notes = {n["en"] for t in self.shown()[page]["notes"].values() for n in t}
        self.assertEqual(notes, {"bergamot", "bourbon geranium", "amberwood"})

    def test_a_note_the_dictionary_learned_is_not_lost(self):
        old = {"notes": {"top": [{"name": "Nylon Accord", "confirmed": True}, {"name": "Blackcurrant", "en": "blackcurrant",
                                  "confirmed": True}], "heart": [], "base": []}}
        new = {"notes": {"top": [{"name": "Nylon Accord", "en": "nylon", "confirmed": True},
                                 {"name": "Blackcurrant Buds", "en": "blackcurrant bud", "confirmed": True}],
                         "heart": [], "base": []}}
        self.assertEqual(self.gate.lost_notes(old, new), [])
        self.assertEqual(self.gate.lost_notes(new, {"notes": {"top": [], "heart": [], "base": []}}), ["blackcurrant bud", "nylon"])

    def test_page_that_would_disappear_stays(self):
        pid = self.pid("Sauvage")
        self.con.execute("DELETE FROM catalog WHERE id=?", (pid,))
        self.run_gate()
        self.assertIn(pid, self.shown())
        self.assertEqual(self.gate.open_items(self.con)[0]["kind"], "gone")

    def test_safety_brake(self):
        for i in range(12):
            self.perfume(self.con, "Brand", f"Perfume {chr(65 + i)}", install=f"x{i}")
        catalog.build(self.con)
        self.run_gate()
        self.assertEqual(len(self.shown()), 14)
        # A broken rebuild renames all of them at once: nothing at all changes on the website.
        self.con.execute("UPDATE catalog SET name = name || ' Wrong'")
        self.perfume(self.con, "Prada", "Luna Rossa Ocean", install="new")
        catalog.build(self.con)
        self.con.execute("UPDATE catalog SET name = name || ' Wrong'")
        line = self.run_gate(now=1000)
        self.assertIn("BRAKE", line)
        self.assertEqual(len(self.shown()), 14)                               # not even the new perfume
        self.assertTrue(self.gate.status(self.con)["brake"])
        self.con.execute("UPDATE catalog SET name = replace(name, ' Wrong', '')")
        self.assertIn("BRAKE", self.run_gate(now=2000))                         # stays on until approved
        self.gate.decide(self.con, "*", "brake", "", "reject")
        self.assertIn("BRAKE", self.run_gate(now=3000))
        self.assertTrue(self.gate.decide(self.con, "*", "brake", "", "approve", now=4000))
        self.assertIsNone(self.gate.status(self.con)["brake"])
        self.assertIn("Luna Rossa Ocean", [p["name"] for p in self.shown().values()])

    def test_nightly_name_fix_only_removes_words(self):
        self.perfume(self.con, "Hugo Boss", "Bottled Parfum (Neutral Box)", install="c")
        catalog.build(self.con)
        self.run_gate()
        pid = self.gate.open_items(self.con)[0]["id"]
        self.run_gate(fixes={pid: "Bottled Something Else"})                    # adds words: ignored
        self.assertNotIn(pid, self.shown())
        self.run_gate(fixes={pid: "Bottled Parfum"})
        self.assertEqual(self.shown()[pid]["name"], "Bottled Parfum")
        self.assertEqual(self.gate.keep_words("Olfactories - Compulsion - Neutral", "olfactories compulsion"),
                         "Olfactories Compulsion")
        self.assertEqual(self.gate.keep_words("Acqua di Giò (100 ml)", "Acqua di Gio"), "Acqua di Giò")
        self.assertEqual(self.gate.keep_words("Sauvage", "Sauvage Elixir"), "")
        self.assertTrue(self.gate.deletion_only("Bottled Parfum (Neutral Box)", "Bottled Parfum"))
        self.assertFalse(self.gate.deletion_only("Bottled", "Bottled Intense"))


if __name__ == "__main__":
    unittest.main()
