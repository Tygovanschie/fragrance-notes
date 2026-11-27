"""Tests for missing.py (the "missing notes" list on the review page). Run: python test_missing.py"""
import json
import sqlite3
import unittest

import catalog
import missing
import obf


def db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    catalog.init(con)
    for i, (brand, name, conf, shops, notes) in enumerate(rows):
        data = {"notes": {"top": [{"name": n} for n in notes], "heart": [], "base": []}, "shopList": shops}
        con.execute("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"p{i}", brand, name, "edp", None, name.lower(), len(shops), 1, conf, "", json.dumps(data), 0))
    return con


ROWS = [("Dior", "Sauvage", 3, ["douglas.nl", "notino.nl"], ["bergamot"]),          # has a page: not listed
        ("Dior", "Addict", 0, ["douglas.nl"], []),
        ("Viktor&Rolf", "Spicebomb Extreme", 2, ["douglas.nl", "notino.nl"], ["tobacco"]),
        ("Van Gils", "Strictly", 0, ["douglas.nl"], ["lavender", "cedar"]),
        ("Joop!", "Le Bain", 0, ["douglas.nl", "notino.nl"], []),
        ("Enchanteur", "Romantic", 0, [obf.SOURCE], [])]


class Todo(unittest.TestCase):
    def test_groups_and_order(self):
        brand, shops = missing.todo(db(ROWS), page_min=3)
        self.assertEqual([x["name"] for x in brand], ["Spicebomb Extreme", "Addict"])     # closest to a page first
        self.assertIn("dior.com", brand[1]["sites"])
        # one shop already named notes: a second shop confirms them, so it comes first
        self.assertEqual([x["name"] for x in shops][0], "Strictly")
        self.assertNotIn("Sauvage", [x["name"] for x in brand + shops])
        self.assertEqual(shops[-1]["seen"], [])                                             # Open Beauty Facts is no shop

    def test_a_source_that_already_sent_its_notes_is_not_offered_again(self):
        con = db([("Tom Ford", "Azure Lime", 2, ["tomfordbeauty.com"], ["lime", "cardamom"]),
                  ("Van Gils", "Strictly", 0, ["douglas.nl"], ["lavender"])])
        brand, shops = missing.todo(con, page_min=3)
        self.assertEqual(brand, [])
        self.assertEqual([x["name"] for x in shops], ["Azure Lime", "Strictly"])
        page = missing.html_page(con, "k" * 30, page_min=3)
        strictly = page[page.index("Strictly"):]
        self.assertIn("notino.nl/search", strictly)
        self.assertNotIn("douglas.nl/nl/search", strictly)

    def test_top_for_the_email(self):
        con = db(ROWS + [("Tom Ford", "Azure Lime", 2, ["tomfordbeauty.com"], ["lime"])])
        t = missing.top(con, 3, page_min=3)
        self.assertEqual([x["item"] for x in t], ["Viktor&Rolf Spicebomb Extreme (edp)", "Tom Ford Azure Lime (edp)",
                                                  "Dior Addict (edp)"])                    # 2/3 first, brand before shop
        self.assertEqual(t[0]["links"][0][0], "Brand site")
        self.assertEqual([l[0] for l in t[1]["links"]], ["Douglas", "Notino"])

    def test_page_escapes_and_links(self):
        con = db(ROWS + [("<b>Evil</b>", "<script>x</script>", 0, ["douglas.nl"], [])])
        page = missing.html_page(con, "k" * 30, page_min=3)
        self.assertNotIn("<script>x", page)
        self.assertIn("site%3Adior.com", page)
        self.assertIn("notino.nl/search.asp?exps=Van+Gils+Strictly+Eau+de+Parfum", page)
        self.assertIn("/review?key=" + "k" * 30, page)


if __name__ == "__main__":
    unittest.main()
