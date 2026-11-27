"""Tests for related.py (other versions and similar perfumes). Run: python test_related.py"""
import unittest

import related


def perfume(pid, brand, name, top=(), heart=(), base=(), conc="edp"):
    tier = lambda ns: [{"name": n, "en": n, "key": n, "confirmed": True, "shops": 2} for n in ns]
    return {"id": pid, "brand": brand, "name": name, "conc": conc, "families": [],
            "notes": {"top": tier(top), "heart": tier(heart), "base": tier(base)}}


SAUVAGE = perfume("a", "Dior", "Sauvage", ["bergamot", "pepper"], ["lavender", "geranium"], ["ambroxan", "vetiver"], "edt")
SAUVAGE_P = perfume("b", "Dior", "Sauvage", ["bergamot", "mandarin"], ["lavender"], ["sandalwood", "vanilla"], "parfum")
SWY = perfume("c", "Emporio Armani", "Stronger With You", ["pink pepper", "cardamom"], ["sage"], ["chestnut", "vanilla"])
SWY_ABS = perfume("d", "Armani", "Stronger With You Absolutely", ["bergamot"], ["lavender"], ["chestnut", "vanilla"])
CODE = perfume("e", "Armani", "Code", ["bergamot"], ["olive tree"], ["tonka bean"])
BOTTLED = perfume("f", "Hugo Boss", "Boss Bottled", ["apple", "bergamot"], ["geranium", "cinnamon"], ["vetiver", "cedar"])
NIGHT = perfume("g", "Hugo Boss", "Boss Bottled Night", ["lavender"], ["violet leaf"], ["musk", "birch"])
ROSE = perfume("h", "Lancôme", "Idôle", ["pear"], ["rose", "jasmine"], ["white musk"])
ALL = [SAUVAGE, SAUVAGE_P, SWY, SWY_ABS, CODE, BOTTLED, NIGHT, ROSE]


class Lines(unittest.TestCase):
    def test_flankers_and_concentrations_are_one_line(self):
        v = related.lines(ALL)
        self.assertEqual(v["a"], ["b"])                      # Sauvage EDT <-> Parfum
        self.assertEqual(v["c"], ["d"])                      # brand spellings don't matter
        self.assertEqual(v["d"], ["c"])
        self.assertEqual(v["f"], ["g"])                      # "Boss" is a brand word, "Bottled" the line
        self.assertNotIn("e", v)                             # Code is no Stronger With You
        self.assertNotIn("h", v)

    def test_a_collection_is_not_a_line(self):
        many = [perfume("r", "Prada", "Olfactories")] + [perfume(f"o{i}", "Prada", f"Olfactories Name {i}") for i in range(9)]
        self.assertEqual(related.lines(many), {})


class Similar(unittest.TestCase):
    def test_shared_notes_and_not_its_own_line(self):
        s = related.similar(ALL)
        ids = [j for j, _, _ in s["a"]]
        self.assertNotIn("b", ids)                           # Sauvage Parfum is a version, not "similar"
        self.assertEqual(ids[0], "f")                        # Boss Bottled: bergamot, geranium, vetiver
        self.assertNotIn("h", ids)                           # nothing in common with a rose-pear perfume
        self.assertEqual(s["a"][0][2][:3], ["vetiver", "geranium", "bergamot"])   # base notes weigh most
        self.assertEqual(s["h"], [])

    def test_a_precise_note_counts_for_its_general_one(self):
        a = perfume("x", "A", "One", ["pink pepper"], ["iris"], ["vanilla"])
        b = perfume("y", "B", "Two", ["pepper"], ["iris"], ["vanilla"])
        v = related.note_vector(a)
        self.assertEqual(v["pepper"], v["pink pepper"] * related.PARENT_W)
        self.assertEqual(related.similar([a, b])["x"] and related.similar([a, b])["x"][0][0], "y")


if __name__ == "__main__":
    unittest.main()
