"""The "missing notes" list on the private review page (/review/notes?key=…): perfumes in the catalog that don't have
enough confirmed notes for a page yet, with links to where the extension can read them in Tygo's own browser.

Nothing here fetches anything: the server only builds links. The notes arrive the normal way, when someone with the
"Help build the open perfume database" setting on opens the page.

- Brand site: one visit is enough, because notes from the brand's own website count as confirmed (catalog.OFFICIAL_SITES,
  the same list as OFFICIAL_SITES in settings.js). The link is a web search limited to the brand's domains, since the
  server doesn't keep page addresses.
- Shops: a note is confirmed once two different shops list it, so the list says which shops already did.
"""
import html
import json
from urllib.parse import quote_plus

import catalog
import obf

SHOW = 60
SHOPS = (("Douglas", "douglas.nl", "https://www.douglas.nl/nl/search?q="),
         ("Notino", "notino.nl", "https://www.notino.nl/search.asp?exps="))
CONC = {"edp": "Eau de Parfum", "edt": "Eau de Toilette", "parfum": "Parfum", "edc": "Eau de Cologne",
        "extrait": "Extrait de Parfum", "elixir": "Elixir"}


def brand_sites():
    """{brand_key: [domains]} for the brands with an official site the extension reads."""
    out = {}
    for d, b in catalog.OFFICIAL_SITES.items():
        out.setdefault(catalog.brand_key(b), []).append(d)
    return out


def todo(con, page_min=catalog.PAGE_CONFIRMED):
    """(brand, shops): perfumes without a page, closest to one first. Each item: id, brand, name, conc, confirmed,
    named (notes any source names), seen (shops that sent facts), sites (brand domains, empty when there is none or it already sent its notes)."""
    sites = brand_sites()
    brand, shops = [], []
    for r in con.execute("SELECT id, brand, name, conc, shops, reports, confirmed, data FROM catalog WHERE confirmed < ?",
                         (page_min,)):
        d = json.loads(r["data"])
        seen = [s for s in d.get("shopList", []) if s != obf.SOURCE]
        named = sum(len(t) for t in d.get("notes", {}).values())
        own = sites.get(catalog.brand_key(r["brand"]), [])
        if set(own) & set(seen):   # the brand site already sent what it has: another visit adds nothing
            own = []
        it = {"id": r["id"], "brand": r["brand"], "name": r["name"], "conc": r["conc"], "confirmed": r["confirmed"],
              "named": named, "seen": seen, "pop": r["shops"] + r["reports"],
              "sites": own}
        (brand if it["sites"] else shops).append(it)
    brand.sort(key=lambda x: (-x["confirmed"], -x["pop"], -x["named"], x["brand"], x["name"]))
    # Without a brand site a note needs a second shop: perfumes whose notes one shop already named come first.
    shops.sort(key=lambda x: (-x["confirmed"], -(x["named"] > 0 and len(x["seen"]) == 1), -x["pop"], -x["named"],
                              x["brand"], x["name"]))
    return brand, shops


def _query(it):
    return f'{it["brand"]} {it["name"]} {CONC.get(it["conc"], "")}'.strip()


def html_page(con, key, page_min=catalog.PAGE_CONFIRMED):
    E = html.escape
    brand, shops = todo(con, page_min)

    def row(it, links):
        state = f'{it["confirmed"]} of {page_min} confirmed' + (f', {it["named"]} named' if it["named"] else ", no notes yet")
        seen = f' · seen at {E(", ".join(it["seen"]))}' if it["seen"] else ""
        return (f'<li><p><b>{E(it["brand"])}</b> {E(it["name"])} <span class="muted">{E(it["conc"])}</span><br>'
                f'<span class="muted">{E(state)}{seen}</span></p><div class="b">{links}</div></li>')

    def brand_links(it):
        q = " OR ".join(f"site:{d}" for d in it["sites"][:4]) + f' {it["name"]}'
        return f'<a class="go" href="https://www.google.com/search?q={quote_plus(q)}" target="_blank" rel="noreferrer">Brand site</a>'

    def shop_links(it):
        q = quote_plus(_query(it))
        new = [s for s in SHOPS if s[1] not in it["seen"]] or SHOPS   # a shop that already sent facts adds nothing
        return "".join(f'<a class="go" href="{u}{q}" target="_blank" rel="noreferrer">{n}</a>' for n, _, u in new)

    def block(title, sub, items, links):
        if not items:
            return ""
        more = f'<p class="muted">… and {len(items) - SHOW} more.</p>' if len(items) > SHOW else ""
        return (f'<h2>{E(title)} ({len(items)})</h2><p class="muted">{sub}</p>'
                f'<ul>{"".join(row(it, links(it)) for it in items[:SHOW])}</ul>{more}')

    body = (block("One visit to the brand site is enough",
                  "Notes on the brand's own product page count as confirmed straight away. Open the product page "
                  "(the link searches the brand's site), wait for the panel, done.", brand, brand_links)
            + block("Needs a second shop",
                    "No brand site in the list, so a note needs two different shops. Pick a shop that isn't under "
                    "\"seen at\".", shops, shop_links)) or "<p>Every perfume in the catalog has a page.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Missing notes | Fragrance Notes</title><style>
body{{margin:0;background:#f4eef3;color:#2b1426;font:16px/1.5 system-ui,sans-serif}}main{{max-width:860px;margin:0 auto;padding:24px 16px 60px}}
h1{{font-size:1.8rem;margin:0 0 4px}}h2{{font-size:1.15rem;margin:28px 0 4px}}ul{{list-style:none;margin:10px 0 0;padding:0}}
li{{background:#fff;border:1px solid #e3d6e0;border-radius:14px;padding:12px 14px;margin:0 0 10px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}}
li p{{margin:0;flex:1 1 380px;overflow-wrap:anywhere}}.b{{display:flex;gap:8px;flex-wrap:wrap}}a{{color:#7e2f63}}
.go{{background:#7e2f63;color:#fff;border-radius:999px;padding:8px 14px;font:600 .9rem system-ui;text-decoration:none}}
.muted{{color:#5e4a59;font-size:.9rem}}</style></head><body><main>
<p><a href="/review?key={E(quote_plus(key))}">← Review</a></p>
<h1>Missing notes</h1><p class="muted">Perfumes in the database without a page yet: a page needs {page_min} confirmed notes.
The extension reads the notes in your browser when "Help build the open perfume database" is on (Settings → Data).
The catalog rebuilds every hour, so a perfume leaves this list within the hour after it has enough.</p>
{body}</main></body></html>"""
