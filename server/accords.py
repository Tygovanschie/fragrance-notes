"""Main accords worked out from a perfume's notes and the fragrance families shops give.

Fragrantica's accords are votes of its own members and may not be copied, so these are our own: every note of
catalog.NOTE_WORDS belongs to one or more accords (vanilla: vanilla and sweet; cardamom: fresh spicy, aromatic and
a little warm spicy), weighed by how sure the note is (confirmed by 2+ shops or named by one), where it sits (base
notes last longest and count a bit more) and the families shops give ("Kruidig", "Oriëntaal"). The result is
scaled so the strongest accord is 100. Notes the table doesn't know are left out.
"""

# accord: (colour, text colour on it)
COLOURS = {
    "sweet": ("#e5447a", "#fff"), "vanilla": ("#f2d9a6", "#3b2a12"), "warm spicy": ("#c0392b", "#fff"),
    "fresh spicy": ("#7fae4f", "#fff"), "aromatic": ("#4f8f7a", "#fff"), "woody": ("#8a5a36", "#fff"),
    "citrus": ("#f2c12e", "#3b2a12"), "fruity": ("#f2694a", "#fff"), "floral": ("#f0a6c8", "#3b1a2e"),
    "white floral": ("#efe6ea", "#3b1a2e"), "powdery": ("#d8c3d9", "#3b1a2e"), "amber": ("#c98a2b", "#fff"),
    "musky": ("#c7b8c9", "#2b1426"), "leather": ("#5b3a2e", "#fff"), "gourmand": ("#a8643a", "#fff"),
    "nutty": ("#b8875a", "#fff"), "balsamic": ("#8e5b4a", "#fff"), "green": ("#5aa85a", "#fff"),
    "fresh": ("#9fd8e3", "#123a44"), "aquatic": ("#4fa3d1", "#fff"), "earthy": ("#6b5d3f", "#fff"),
    "smoky": ("#6e6a6f", "#fff"),
}

NOTES = {
    "vanilla": {"vanilla": 1, "sweet": .6}, "bourbon vanilla": {"vanilla": 1, "sweet": .6, "balsamic": .3},
    "tonka bean": {"sweet": .8, "vanilla": .5, "powdery": .5, "warm spicy": .3},
    "chestnut": {"nutty": 1, "sweet": .5, "gourmand": .5}, "glazed chestnut": {"nutty": 1, "sweet": .8, "gourmand": .6},
    "frangipani": {"white floral": 1, "floral": .5, "sweet": .3}, "lavender": {"aromatic": 1, "fresh": .3, "powdery": .2},
    "cinnamon": {"warm spicy": 1, "sweet": .3}, "sage": {"aromatic": 1, "green": .4},
    "pepper": {"fresh spicy": .8, "warm spicy": .4}, "pink pepper": {"fresh spicy": 1, "fruity": .3},
    "black pepper": {"fresh spicy": .8, "warm spicy": .5}, "cardamom": {"fresh spicy": .8, "aromatic": .5, "warm spicy": .3},
    "juniper": {"aromatic": .8, "fresh": .5, "green": .3}, "ginger": {"fresh spicy": 1, "citrus": .3},
    "bergamot": {"citrus": 1, "fresh": .4}, "lemon": {"citrus": 1, "fresh": .5}, "mandarin": {"citrus": 1, "fruity": .3},
    "orange": {"citrus": 1, "fruity": .3}, "grapefruit": {"citrus": 1, "fresh": .4},
    "apple": {"fruity": 1, "fresh": .3}, "pear": {"fruity": 1, "sweet": .3}, "peach": {"fruity": 1, "sweet": .3},
    "cherry": {"fruity": 1, "sweet": .5}, "sour cherry": {"fruity": 1, "sweet": .3}, "blackcurrant": {"fruity": 1, "green": .3},
    "raspberry": {"fruity": 1, "sweet": .4}, "pineapple": {"fruity": 1, "sweet": .3}, "passion fruit": {"fruity": 1, "sweet": .3},
    "coconut": {"sweet": .6, "gourmand": .5, "fruity": .3}, "melon": {"fruity": .8, "aquatic": .4, "fresh": .3},
    "rose": {"floral": 1}, "jasmine": {"white floral": 1, "floral": .4}, "orange blossom": {"white floral": 1, "citrus": .2},
    "tuberose": {"white floral": 1, "sweet": .3}, "violet": {"floral": .7, "powdery": .6},
    "lily of the valley": {"floral": .8, "fresh": .4, "green": .3}, "geranium": {"floral": .6, "green": .4, "aromatic": .4},
    "patchouli": {"earthy": 1, "woody": .5}, "vetiver": {"woody": .8, "earthy": .6, "smoky": .2},
    "sandalwood": {"woody": 1, "sweet": .2}, "cedar": {"woody": 1}, "oud": {"woody": .8, "smoky": .5, "leather": .3},
    "guaiac wood": {"woody": .8, "smoky": .6}, "amberwood": {"woody": .8, "amber": .7},
    "amber": {"amber": 1, "warm spicy": .3, "sweet": .3}, "musk": {"musky": 1, "powdery": .3},
    "leather": {"leather": 1, "smoky": .3}, "suede": {"leather": .8, "powdery": .3, "musky": .3},
    "tobacco": {"smoky": .5, "sweet": .4, "warm spicy": .4, "earthy": .3},
    "honey": {"sweet": 1, "gourmand": .3}, "caramel": {"sweet": 1, "gourmand": .7}, "toffee": {"sweet": 1, "gourmand": .7},
    "maple syrup": {"sweet": 1, "gourmand": .6}, "coffee": {"gourmand": 1, "smoky": .2}, "cocoa": {"gourmand": 1, "sweet": .4},
    "chocolate": {"gourmand": 1, "sweet": .6}, "almond": {"nutty": 1, "sweet": .4},
    "benzoin": {"balsamic": 1, "amber": .5, "vanilla": .3}, "incense": {"smoky": 1, "balsamic": .5},
    "myrrh": {"balsamic": 1, "smoky": .4}, "oakmoss": {"green": .7, "earthy": .7},
    "mint": {"fresh": 1, "aromatic": .5}, "violet leaf": {"green": 1, "fresh": .4},
    "basil": {"aromatic": .8, "green": .5}, "rosemary": {"aromatic": 1, "fresh": .3}, "tea": {"green": .6, "fresh": .5, "aromatic": .3},
    "saffron": {"warm spicy": .8, "leather": .3, "sweet": .2}, "clove": {"warm spicy": 1}, "nutmeg": {"warm spicy": 1},
}

# Notes added on 2026-11-25 with the larger dictionary.
NOTES.update({
    "iris": {"powdery": 1, "floral": .5, "earthy": .2}, "neroli": {"white floral": .7, "citrus": .6, "fresh": .3},
    "petitgrain": {"citrus": .8, "green": .5, "aromatic": .3}, "ylang ylang": {"white floral": 1, "sweet": .3},
    "magnolia": {"floral": 1, "citrus": .2}, "peony": {"floral": 1, "fresh": .3}, "freesia": {"floral": 1, "fresh": .4},
    "lily": {"white floral": .8, "floral": .5}, "water lily": {"floral": .7, "aquatic": .6},
    "lotus": {"floral": .7, "aquatic": .5}, "gardenia": {"white floral": 1, "sweet": .2},
    "osmanthus": {"floral": .8, "fruity": .5, "leather": .2}, "mimosa": {"floral": .8, "powdery": .6},
    "lilac": {"floral": 1, "powdery": .3}, "hyacinth": {"floral": .8, "green": .5},
    "narcissus": {"floral": .8, "green": .3, "earthy": .2}, "orchid": {"floral": 1, "sweet": .3},
    "honeysuckle": {"floral": .9, "sweet": .4}, "heliotrope": {"powdery": .9, "sweet": .5, "floral": .3},
    "carnation": {"floral": .7, "warm spicy": .6}, "cyclamen": {"floral": .8, "fresh": .4},
    "champaca": {"white floral": .9, "fruity": .3}, "ambrette": {"musky": 1, "fruity": .3},
    "lime": {"citrus": 1, "fresh": .5}, "yuzu": {"citrus": 1, "fresh": .4},
    "bitter orange": {"citrus": 1, "green": .3}, "blood orange": {"citrus": 1, "fruity": .4},
    "blood mandarin": {"citrus": 1, "fruity": .4}, "clementine": {"citrus": 1, "fruity": .3},
    "lemon verbena": {"citrus": .8, "aromatic": .5, "green": .3}, "lemongrass": {"citrus": .8, "green": .5},
    "fig": {"green": .7, "fruity": .6, "sweet": .3}, "banana": {"fruity": 1, "sweet": .4}, "mango": {"fruity": 1, "sweet": .4},
    "lychee": {"fruity": 1, "floral": .3}, "blackberry": {"fruity": 1, "sweet": .3}, "strawberry": {"fruity": 1, "sweet": .5},
    "apricot": {"fruity": 1, "sweet": .3}, "plum": {"fruity": 1, "sweet": .4}, "quince": {"fruity": 1, "fresh": .3},
    "rhubarb": {"fruity": .7, "green": .6, "fresh": .3}, "red berries": {"fruity": 1, "sweet": .4},
    "nectarine": {"fruity": 1, "sweet": .3}, "pomegranate": {"fruity": 1, "fresh": .3},
    "cucumber": {"green": .8, "fresh": .6, "aquatic": .3}, "pistachio": {"nutty": 1, "gourmand": .5, "sweet": .3},
    "hazelnut": {"nutty": 1, "gourmand": .5, "sweet": .3}, "praline": {"gourmand": 1, "nutty": .6, "sweet": .6},
    "marshmallow": {"sweet": 1, "gourmand": .6, "powdery": .3}, "sugar": {"sweet": 1, "gourmand": .4},
    "milk": {"gourmand": .7, "sweet": .4, "powdery": .3}, "cream": {"gourmand": .7, "sweet": .5},
    "licorice": {"sweet": .6, "gourmand": .5, "warm spicy": .3}, "rum": {"sweet": .5, "gourmand": .5, "warm spicy": .3},
    "cognac": {"sweet": .4, "woody": .4, "fruity": .3}, "whiskey": {"smoky": .5, "woody": .5, "sweet": .3},
    "wine": {"fruity": .6, "sweet": .3}, "champagne": {"fresh": .6, "fruity": .4},
    "anise": {"fresh spicy": .6, "sweet": .4, "aromatic": .3}, "star anise": {"fresh spicy": .6, "sweet": .4, "aromatic": .3},
    "coriander": {"fresh spicy": .8, "aromatic": .4}, "cumin": {"warm spicy": .9, "earthy": .3},
    "caraway": {"fresh spicy": .7, "warm spicy": .3}, "tarragon": {"aromatic": .9, "green": .4, "fresh spicy": .2},
    "thyme": {"aromatic": 1, "green": .3}, "bay leaf": {"aromatic": .8, "fresh spicy": .4},
    "clary sage": {"aromatic": 1, "green": .3}, "davana": {"fruity": .6, "aromatic": .5},
    "wormwood": {"aromatic": .9, "green": .5}, "elemi": {"balsamic": .6, "citrus": .5, "fresh spicy": .3},
    "galbanum": {"green": 1, "earthy": .3}, "frankincense": {"smoky": .8, "balsamic": .6, "citrus": .2},
    "labdanum": {"amber": .9, "balsamic": .6, "leather": .3}, "resin": {"balsamic": 1, "amber": .5},
    "ambergris": {"amber": .7, "musky": .5, "aquatic": .3}, "ambroxan": {"amber": .9, "woody": .5, "musky": .3},
    "cashmeran": {"woody": .8, "musky": .5, "powdery": .2}, "iso e super": {"woody": 1, "amber": .3},
    "hedione": {"white floral": .7, "fresh": .5}, "aldehydes": {"fresh": .7, "powdery": .6},
    "white musk": {"musky": 1, "powdery": .4, "fresh": .2}, "civet": {"musky": .8, "leather": .5},
    "castoreum": {"leather": .9, "musky": .5}, "birch": {"smoky": .7, "leather": .6, "woody": .4},
    "cypress": {"woody": .8, "green": .5, "aromatic": .3}, "pine": {"woody": .6, "green": .6, "fresh": .4},
    "fir": {"woody": .6, "green": .5, "balsamic": .4}, "oak": {"woody": 1, "smoky": .2},
    "mahogany": {"woody": 1}, "rosewood": {"woody": .8, "floral": .4}, "ebony": {"woody": 1, "smoky": .3},
    "olive tree": {"woody": .6, "green": .5}, "papyrus": {"woody": .7, "earthy": .5, "smoky": .3},
    "moss": {"green": .8, "earthy": .7}, "hay": {"green": .5, "sweet": .4, "earthy": .3}, "grass": {"green": 1, "fresh": .4},
    "smoke": {"smoky": 1}, "salt": {"aquatic": .7, "fresh": .4}, "mineral": {"fresh": .6, "aquatic": .4, "earthy": .3},
    "ozonic": {"fresh": .9, "aquatic": .6}, "marine": {"aquatic": 1, "fresh": .5}, "solar notes": {"white floral": .5, "sweet": .4, "aquatic": .3},
    "caviar": {"aquatic": .7, "fresh": .3}, "monoi": {"white floral": .8, "sweet": .4, "gourmand": .3},
    "amberever": {"woody": .9, "amber": .8}, "berries": {"fruity": 1, "sweet": .4},
    "allspice": {"warm spicy": 1, "sweet": .2}, "cinnamon liqueur": {"warm spicy": .9, "sweet": .6, "gourmand": .4},
})

# Notes found without accords in the catalog on 2026-11-26.
NOTES.update({
    "lavandin": {"aromatic": 1, "fresh": .4, "powdery": .1}, "peppermint": {"fresh": 1, "aromatic": .6},
    "sichuan pepper": {"fresh spicy": 1, "citrus": .4}, "calone": {"aquatic": 1, "fresh": .5, "fruity": .2},
    "calypsone": {"aquatic": .8, "fruity": .4, "fresh": .3}, "meringue": {"sweet": 1, "gourmand": .6, "vanilla": .3},
    "kulfi": {"sweet": .7, "gourmand": .6, "nutty": .4, "warm spicy": .2}, "belambre": {"woody": 1, "amber": .5},
})
FAMILIES = {
    "spicy": {"warm spicy": .6, "fresh spicy": .3}, "oriental": {"amber": .8, "warm spicy": .3, "sweet": .3},
    "woody": {"woody": 1}, "aromatic": {"aromatic": 1}, "floral": {"floral": 1}, "fruity": {"fruity": 1},
    "sweet": {"sweet": 1}, "powdery": {"powdery": 1}, "fresh": {"fresh": 1}, "citrus": {"citrus": 1},
    "aquatic": {"aquatic": 1}, "green": {"green": 1}, "gourmand": {"gourmand": 1, "sweet": .5},
    "chypre": {"earthy": .5, "citrus": .4, "woody": .4}, "fougere": {"aromatic": .8, "green": .3, "woody": .3},
    "musky": {"musky": 1}, "earthy": {"earthy": 1}, "amber": {"amber": 1}, "leather": {"leather": 1},
    "cream": {"sweet": .5, "vanilla": .3, "musky": .2}, "moss": {"earthy": .6, "green": .5},
}

TIER = {"top": 1.0, "heart": 1.0, "base": 1.1}   # base notes last longest, so a little more
DECAY = .6          # per accord, the strongest note counts fully, the next .6, then .36…: five woods aren't five times woody
IN_NAME = 2.0       # a note the perfume is named after (Ombré Leather, Grey Vetiver) counts double
MIN_SHOWN = 30      # accords below this (with the strongest at 100) aren't shown
MAX_SHOWN = 8
MIN_NOTES = 3       # known notes needed before accords are shown at all


def weights(key):
    """The accords of one note. A shop may list a family as a note ("Houtachtige noten" = woody): then the family's
    accords. A note the table doesn't know: the accords of the general note it is a form of (catalog.NOTE_PARENTS)."""
    if key in NOTES:
        return NOTES[key]
    if key in FAMILIES:
        return FAMILIES[key]
    import catalog   # here, not at the top: catalog is the bigger module and doesn't need accords
    return NOTES.get(catalog.NOTE_PARENTS.get(key, ""))


def main_accords(p):
    """[(accord, strength 1-100)] strongest first, or [] when too few known notes. With MIN_NOTES or more confirmed
    known notes, only those count: a note one shop names (often from a different note list) shouldn't colour the
    accords. Each accord adds up its notes with diminishing returns (DECAY), so the accords that make a perfume
    stand out (the pepper in Sauvage) aren't buried under the ones many notes share (woody, earthy)."""
    import catalog
    parts, known = {}, 0
    name = f" {catalog.plain(p.get('name', ''))} "
    all_notes = [n for tier in TIER for n in p.get("notes", {}).get(tier, [])]
    only_confirmed = sum(1 for n in all_notes if n.get("confirmed") and weights(n.get("en") or n.get("key"))) >= MIN_NOTES
    for tier, w in TIER.items():
        for n in p.get("notes", {}).get(tier, []):
            k = n.get("en") or n.get("key")
            m = weights(k)
            if not m or (only_confirmed and not n.get("confirmed")):
                continue
            known += 1
            sure = (1.0 if n.get("confirmed") else 0.4) * (IN_NAME if k and f" {k} " in name else 1)
            for a, x in m.items():
                parts.setdefault(a, []).append(x * w * sure)
    if known < MIN_NOTES:
        return []
    for f in p.get("families", []):
        m = FAMILIES.get(f.get("key")) or NOTES.get(f.get("key"))   # "Amberachtig" is the amber family
        if m:
            sure = 1.0 if f.get("confirmed") else 0.4
            for a, x in m.items():
                parts.setdefault(a, []).append(x * sure)
    score = {a: sum(v * DECAY ** i for i, v in enumerate(sorted(vs, reverse=True))) for a, vs in parts.items()}
    top = max(score.values(), default=0)
    if not top:
        return []
    out = sorted(((a, round(v / top * 100)) for a, v in score.items()), key=lambda t: (-t[1], t[0]))
    return [(a, v) for a, v in out if v >= MIN_SHOWN][:MAX_SHOWN]


NAMES = {
    "en": {a: a for a in COLOURS},
    "nl": {"sweet": "zoet", "vanilla": "vanille", "warm spicy": "warm kruidig", "fresh spicy": "fris kruidig",
           "aromatic": "aromatisch", "woody": "houtig", "citrus": "citrus", "fruity": "fruitig", "floral": "bloemig",
           "white floral": "witte bloemen", "powdery": "poederig", "amber": "amber", "musky": "muskusachtig",
           "leather": "leer", "gourmand": "gourmand", "nutty": "nootachtig", "balsamic": "balsamico", "green": "groen",
           "fresh": "fris", "aquatic": "aquatisch", "earthy": "aards", "smoky": "rokerig"},
    "de": {"sweet": "süß", "vanilla": "Vanille", "warm spicy": "warm würzig", "fresh spicy": "frisch würzig",
           "aromatic": "aromatisch", "woody": "holzig", "citrus": "Zitrus", "fruity": "fruchtig", "floral": "blumig",
           "white floral": "weiße Blüten", "powdery": "pudrig", "amber": "Amber", "musky": "moschusartig",
           "leather": "Leder", "gourmand": "Gourmand", "nutty": "nussig", "balsamic": "balsamisch", "green": "grün",
           "fresh": "frisch", "aquatic": "aquatisch", "earthy": "erdig", "smoky": "rauchig"},
    "fr": {"sweet": "sucré", "vanilla": "vanillé", "warm spicy": "épicé chaud", "fresh spicy": "épicé frais",
           "aromatic": "aromatique", "woody": "boisé", "citrus": "hespéridé", "fruity": "fruité", "floral": "floral",
           "white floral": "fleurs blanches", "powdery": "poudré", "amber": "ambré", "musky": "musqué",
           "leather": "cuir", "gourmand": "gourmand", "nutty": "noisette", "balsamic": "balsamique", "green": "vert",
           "fresh": "frais", "aquatic": "aquatique", "earthy": "terreux", "smoky": "fumé"},
    "es": {"sweet": "dulce", "vanilla": "vainilla", "warm spicy": "especiado cálido", "fresh spicy": "especiado fresco",
           "aromatic": "aromático", "woody": "amaderado", "citrus": "cítrico", "fruity": "afrutado", "floral": "floral",
           "white floral": "flores blancas", "powdery": "atalcado", "amber": "ámbar", "musky": "almizclado",
           "leather": "cuero", "gourmand": "gourmand", "nutty": "a frutos secos", "balsamic": "balsámico", "green": "verde",
           "fresh": "fresco", "aquatic": "acuático", "earthy": "terroso", "smoky": "ahumado"},
    "it": {"sweet": "dolce", "vanilla": "vaniglia", "warm spicy": "speziato caldo", "fresh spicy": "speziato fresco",
           "aromatic": "aromatico", "woody": "legnoso", "citrus": "agrumato", "fruity": "fruttato", "floral": "floreale",
           "white floral": "fiori bianchi", "powdery": "cipriato", "amber": "ambrato", "musky": "muschiato",
           "leather": "cuoio", "gourmand": "gourmand", "nutty": "nocciolato", "balsamic": "balsamico", "green": "verde",
           "fresh": "fresco", "aquatic": "acquatico", "earthy": "terroso", "smoky": "affumicato"},
    "pt": {"sweet": "doce", "vanilla": "baunilha", "warm spicy": "especiado quente", "fresh spicy": "especiado fresco",
           "aromatic": "aromático", "woody": "amadeirado", "citrus": "cítrico", "fruity": "frutado", "floral": "floral",
           "white floral": "flores brancas", "powdery": "atalcado", "amber": "âmbar", "musky": "almiscarado",
           "leather": "couro", "gourmand": "gourmand", "nutty": "de frutos secos", "balsamic": "balsâmico", "green": "verde",
           "fresh": "fresco", "aquatic": "aquático", "earthy": "terroso", "smoky": "fumado"},
    "pl": {"sweet": "słodki", "vanilla": "waniliowy", "warm spicy": "ciepły korzenny", "fresh spicy": "świeży korzenny",
           "aromatic": "aromatyczny", "woody": "drzewny", "citrus": "cytrusowy", "fruity": "owocowy", "floral": "kwiatowy",
           "white floral": "białe kwiaty", "powdery": "pudrowy", "amber": "ambrowy", "musky": "piżmowy",
           "leather": "skórzany", "gourmand": "gourmand", "nutty": "orzechowy", "balsamic": "balsamiczny", "green": "zielony",
           "fresh": "świeży", "aquatic": "wodny", "earthy": "ziemisty", "smoky": "dymny"},
}


def name(accord, lang):
    return NAMES.get(lang, NAMES["en"]).get(accord, accord)
