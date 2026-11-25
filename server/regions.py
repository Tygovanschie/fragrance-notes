"""Which country a shop's price is for, and which prices a visitor sees.

A price's country follows from the shop and the currency, so it is worked out when needed (nothing extra stored):
the shop's domain (douglas.nl -> NL, the same table as TLD_COUNTRY in the extension's settings.js), a few known
.com shops (COM_COUNTRY), else the currency (USD -> US). Euros from an international .com shop: "EU" (somewhere in
the eurozone). Prices are never converted or mixed: the same bottle costs differently per country (VAT, shipping).
"""

TLD_COUNTRY = {"nl": "NL", "be": "BE", "de": "DE", "at": "AT", "ch": "CH", "fr": "FR", "it": "IT", "es": "ES", "pt": "PT",
               "pl": "PL", "cz": "CZ", "sk": "SK", "ro": "RO", "hu": "HU", "hr": "HR", "si": "SI", "bg": "BG", "lt": "LT",
               "lv": "LV", "ee": "EE", "gr": "GR", "se": "SE", "dk": "DK", "no": "NO", "fi": "FI", "ie": "IE", "lu": "LU",
               "uk": "GB", "co.uk": "GB", "au": "AU", "com.au": "AU", "nz": "NZ", "co.nz": "NZ", "ca": "CA", "ae": "AE",
               "sa": "SA", "sg": "SG", "my": "MY", "jp": "JP", "kr": "KR", "co.kr": "KR", "com.br": "BR", "br": "BR",
               "tr": "TR", "com.tr": "TR", "mx": "MX", "com.mx": "MX", "ua": "UA", "rs": "RS", "il": "IL", "co.il": "IL"}
COM_COUNTRY = {"sephora.com": "US", "ulta.com": "US", "saks.com": "US", "saksfifthavenue.com": "US",
               "bloomingdales.com": "US", "luckyscent.com": "US", "aedes.com": "US", "harrods.com": "GB",
               "theperfumeshop.com": "GB", "mecca.com": "AU", "galerieslafayette.com": "FR", "lebonmarche.com": "FR",
               "jovoyparis.com": "FR", "noseparis.com": "FR"}
CUR_COUNTRY = {"USD": "US", "GBP": "GB", "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CHF": "CH", "SEK": "SE", "NOK": "NO",
               "DKK": "DK", "PLN": "PL", "CZK": "CZ", "HUF": "HU", "RON": "RO", "BGN": "BG", "AED": "AE", "SAR": "SA",
               "SGD": "SG", "JPY": "JP", "KRW": "KR", "BRL": "BR", "TRY": "TR", "MXN": "MX", "EUR": "EU"}
EUROZONE = {"AT", "BE", "HR", "CY", "EE", "FI", "FR", "DE", "GR", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PT", "SK",
            "SI", "ES", "EU"}
ZONE = "EUZ"   # the whole eurozone together, as a choice in the menu


def country_of(shop, currency):
    """The country a price at this shop in this currency is for ("EU": euros, country unknown)."""
    s = str(shop or "").lower().removeprefix("www.")
    if s in COM_COUNTRY:
        c = COM_COUNTRY[s]
    else:
        parts = s.split(".")
        c = TLD_COUNTRY.get(".".join(parts[-2:])) or TLD_COUNTRY.get(parts[-1]) or ""
    # A .de shop selling in dollars is selling to someone else: the currency wins when they disagree.
    by_cur = CUR_COUNTRY.get(currency, "")
    if not c or (by_cur and by_cur != "EU" and by_cur != c) or (by_cur == "EU" and c not in EUROZONE):
        return by_cur or c
    return c


def flag(code):
    """The flag emoji of a country code; the EU flag for the eurozone."""
    if code in ("EU", ZONE):
        return "\U0001F1EA\U0001F1FA"
    if len(code) == 2 and code.isalpha():
        return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper())
    return ""


def pick(available, visitor=None, region=None):
    """Which prices to show: (countries, kind). available: {country: currency} with prices in the window.
    kind: "home" (the visitor's own country, or the one they picked), "zone" (the eurozone: picked, or the visitor's
    eurozone country has none of its own), "all" (no visitor country known: the most common currency, as before),
    "none" (nothing for the visitor's country or currency)."""
    want = (region or visitor or "").upper()
    euro = {c for c, cur in available.items() if cur == "EUR"}
    if want == ZONE:
        return (euro, "zone") if euro else (set(), "none")
    if want in available:
        return {want}, "home"
    if want in EUROZONE and euro:
        return euro, "zone"
    if not want:
        return None, "all"
    cur = next((k for k, v in CUR_COUNTRY.items() if v == want), None)
    same = {c for c, x in available.items() if cur and x == cur}
    return (same, "home") if same else (set(), "none")
