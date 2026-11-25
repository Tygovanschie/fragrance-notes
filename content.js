// Detects the perfume on a shop page and shows a floating Fragrantica panel.
(() => {
  if (window.__fnLoaded) return;
  window.__fnLoaded = true;

  // "Perfume" in the shop languages we support (Latin-script words use word boundaries).
  const FRAG_RE = /\b(parfums?|perfumes?|perfumy|perfumy|profum[oi]|parf[ée]m|parf[üu]m|eau de|cologne|colonia|edp|edt|extrait|fragrances?|fragancia|fragranza|geur|duft|doft|tuoksu|illat|koku|vůně|zapach)\b|духи|парфюм|туалетн|парфум|άρωμα|香水|フレグランス|향수|عطر|בושם/i;

  // Parts of a page about other products, or the site's own chrome (same list as readPrices uses).
  const OTHER_PRODUCTS_SEL = '[class*="related" i],[class*="recommend" i],[class*="carousel" i],[class*="slider" i],[class*="upsell" i],[class*="cross-sell" i],[class*="similar" i],[class*="product-tile" i],[class*="productcard" i],[class*="product-card" i],[class*="recently" i],header,footer,nav,aside';

  // ---------- product detection ----------
  function collectProducts(d, out) {
    if (!d) return;
    if (Array.isArray(d)) return d.forEach(x => collectProducts(x, out));
    if (typeof d !== 'object') return;
    const types = [].concat(d['@type'] || []);
    if (types.includes('Product') || types.includes('ProductGroup')) out.push(d);
    if (d['@graph']) collectProducts(d['@graph'], out);
  }

  function readJsonLd() {
    const out = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
      try { collectProducts(JSON.parse(s.textContent), out); } catch {}
    });
    return out.find(p => p.name);
  }

  // Some shops (e.g. Sephora) mark products up with schema.org microdata instead of JSON-LD.
  function readMicrodata() {
    const root = document.querySelector('[itemtype$="schema.org/Product"], [itemtype$="schema.org/IndividualProduct"]');
    if (!root) return null;
    const val = el => (el ? (el.getAttribute('content') || el.textContent || '').replace(/\s+/g, ' ').trim() : '');
    const brandEl = root.querySelector('[itemprop="brand"]');
    const brand = brandEl ? (val(brandEl.querySelector('[itemprop="name"]')) || val(brandEl)) : '';
    const offers = [...root.querySelectorAll('[itemprop="offers"]')].map(o => ({
      name: val(o.querySelector('[itemprop="name"]')) || val(o.querySelector('[itemprop="sku"]')),
      price: val(o.querySelector('[itemprop="price"]')) || val(o.querySelector('[itemprop="lowPrice"]')),
      priceCurrency: val(o.querySelector('[itemprop="priceCurrency"]'))
    }));
    // The first itemprop=name is often the brand's, so only trust a product name that differs from it.
    const names = [...root.querySelectorAll('[itemprop="name"]')].filter(e => !brandEl?.contains(e)).map(val);
    return { name: names.find(n => n && n.toLowerCase() !== brand.toLowerCase()) || '', brand, offers, microdata: true };
  }
  // Amazon has no structured product data; read its product title, brand and price instead.
  function readAmazon() {
    if (!/(^|\.)amazon\./.test(location.hostname)) return null;
    const title = document.querySelector('#productTitle')?.textContent.trim();
    if (!title) return null;
    const row = [...document.querySelectorAll('#productOverview_feature_div tr, #detailBullets_feature_div li, #productDetails_techSpec_section_1 tr')]
      .map(r => r.textContent.replace(/\s+/g, ' ').trim()).find(t => /^(brand|merk|marke|marque|marca|marka|varumärke)\b/i.test(t));
    let brand = row ? row.replace(/^\S+\s*:?\s*/, '') : (document.querySelector('#bylineInfo')?.textContent || '')
      .replace(/^(visit the|besuche den|bezoek de|visitez la boutique|visita lo store di|visita la tienda de|brand:|merk:|marke:|marque\s?:|marca:)\s*/i, '')
      .replace(/(\s*-?\s*(store|shop|winkel|boutique|tienda))$/i, '').trim();
    const priceText = document.querySelector('#corePrice_feature_div .a-offscreen, #corePriceDisplay_desktop_feature_div .a-offscreen, .a-price .a-offscreen')?.textContent || '';
    const price = parseFloat(priceText.replace(/[^\d.,]/g, '').replace(/[.,](?=\d{3}\b)/g, '').replace(',', '.'));
    const currency = /€/.test(priceText) ? 'EUR' : /£/.test(priceText) ? 'GBP' : /\$/.test(priceText) ? 'USD' : undefined;
    return { '@type': 'Product', name: title, brand: brand ? { name: brand } : undefined,
      offers: price > 0 ? [{ price, priceCurrency: currency, name: title }] : [] };
  }

  const readProduct = () => readJsonLd() || readMicrodata() || readAmazon();

  const brandName = b => {
    if (Array.isArray(b)) b = b[0];
    return (typeof b === 'string' ? b : b?.name || '').trim();
  };
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const withoutBrand = (name, brand) => brand ? (' ' + name + ' ').replace(new RegExp('\\s' + escRe(brand) + '\\s', 'i'), ' ') : name;

  // Some shops (e.g. Sephora) put a description behind the name: "Sauvage - Eau de Parfum für Herren - Würzige Noten".
  // Keep the first part and any later part that isn't descriptive.
  const DESC_RE = /\b(noten|notes?|n[oó]tes?|akkord\w*|f[üu]r|for|pour|per|para|voor|herren\w*|damen\w*|men'?s?|women'?s?|homme|femme|unisex|duft\w*|geur|holz\w*|blumig\w*|fruchtig\w*|w[üu]rzig\w*|frisch\w*|floral|woody|spicy|fresh|fruity|sweet|limit\w*|edition|geschenk\w*|set|gift)\b|herrenduft|damenduft|herrenparfum|damenparfum|[&,]/i;
  function trimDescription(name) {
    const parts = String(name || '').split(/\s+[-–—]\s+/);
    if (parts.length < 2) return name;
    return [parts[0], ...parts.slice(1).filter(p => FN.detectConc(p) && !/[\p{L}]{3,}/u.test(FN.stripConc(p)) ? true : !DESC_RE.test(p))].join(' - ');
  }

  // Products of a perfume line that aren't the perfume itself, in the shop languages.
  const NOT_FRAG_RE = /\b(deodorant|deodorants|d[ée]odorant|desodorante|deodorante|dezodorant|deo ?(spray|stick|roller|roll ?on)|deostick|anti-?transpira\w*|antiperspirant|shower ?(gel|cream|foam|oil)|douche ?(gel|cr[eè]me|schuim)|hair ?(&|and|en|und|et) ?body|body ?(wash|cream|butter|scrub|oil)|bodywash|bodycr[eè]me|shampoo|hand ?cr[eè]me|handcr[eè]me|hand ?cream|beard ?oil|duschgel|gel douche|gel de ducha|body ?lotion|lotion pour le corps|k[öo]rperlotion|bodymilk|body ?mist|body ?spray|haarparfum|hair ?(mist|perfume)|after ?shave\w*|zeep|seife|savon|soap|bath ?(gel|oil)|badschuim|kaars|kerze|bougie|candle)\b/i;

  // Gift sets, in the shop languages ("Geschenkset", "cadeauset", "coffret", "gift box", Turkish "seti").
  const SET_RE = /\b(sets?|giftsets?|gift ?box|gift set|geschenk(set|box|packung)|cadeau(set|doos)|kerst(set|pakket)|coffrets?|kit|confezione regalo|estuche|zestaw|seti)\b/i;
  // Shop abbreviations in set contents ("EMPORIO STRONGER WYO EDP SPRAY").
  const ABBR = { wyo: 'With You', swy: 'Stronger With You' };
  const expandAbbr = s => s.replace(/\b[A-Za-z]{3}\b/g, w => ABBR[w.toLowerCase()] || w);
  // The perfume line of a set's contents: a size in ml and a concentration, not shower gel, lotion or a sample.
  function setPerfume() {
    const lines = (document.querySelector('main') || document.body).innerText.split('\n').map(l => l.replace(/^[\s•·*-]+/, '').trim());
    return lines.find(l => l.length < 120
      && /\d+(?:[.,]\d+)?\s?ml\b/i.test(l)
      && /\b(edp|edt|edc|eau de (parfum|toilette|cologne)|parfum|extrait)\b/i.test(l)
      && !/\b(shower|douche|dusch|gel|lotion|balm|baume|deo|deodorant|body|after ?shave|cream|cr[eè]me|smpl|sample|mini|miniature)\b/i.test(l))
      ?.replace(/\(\s*\d+(?:[.,]\d+)?\s?ml\s*\)/i, ' ') || '';
  }

  // Name without brand, sizes, packaging words and concentration (that is added back separately).
  function cleanName(name, brand) {
    let n = withoutBrand(trimDescription(name), brand);
    n = FN.stripConc(n)
      .replace(/(?:\b\d+(?:[.,]\d+)?|[.,]\d+)\s?(?:fl\.?\s?)?(ml|oz|g)\b\.?/gi, ' ')
      .replace(/\b(spray|vapo|vaporisateur|vaporizador|vaporizzatore|zerst[aä]uber|natural spray|navulling|refill|nachf[uü]llung|tester|refillable|rechargeable|recargable|ricaricabile|nachf[uü]llbar|navulbaar|coffret|gift set|geschenkset|for (wo)?men|(wo)?men'?s|pour (homme|femme)|unisex|limited edition)\b/gi, ' ')
      // What's left of "(Refillable)" or "(100 ml)", and shop words ("Acqua di Gio - Eau de Toilette kopen").
      .replace(/\(\s*\)|\[\s*\]/g, ' ')
      .replace(/\s(kopen|bestellen|kaufen|acheter|comprar|acquista)\s*$/i, ' ')
      .replace(/[|•–—,-]+\s*$/, ' ')
      .replace(/^\s*[|•–—,-]+/, ' ');
    return n.replace(/\s+/g, ' ').trim();
  }

  function detect() {
    const p = readProduct();
    let brand = p ? brandName(p.brand) : '';
    // Guard against stale product data after in-page navigation: the brand must appear on the page.
    const h1 = document.querySelector('h1');
    const h1Text = h1 ? (h1.innerText || h1.textContent || '') : '';   // innerText keeps the line break between brand and name
    const visible = `${h1Text} ${document.title}`.toLowerCase();
    if (brand && !visible.includes(brand.toLowerCase())) brand = '';
    // Some shops (e.g. Douglas) put only the size ("90 ml") in the product data,
    // so try several sources and use the first that still has a real name after cleanup.
    const candidates = [
      p?.name,
      h1Text,
      document.querySelector('meta[property="og:title"]')?.content,
      document.title
    ].filter(Boolean).map(s => s.split(/\s[|•]\s|\s✔/)[0].replace(/\s+/g, ' ').trim());
    let name = '', cleaned = '';
    for (const c of candidates) {
      const cl = cleanName(c, brand);
      if (/\p{L}{2,}|[\p{L}\p{N}]{3,}/u.test(cl)) { name = c; cleaned = cl; break; }
    }
    // Concentration: from the chosen name first, then the other sources (and the product's offers).
    const concSources = [name, ...candidates, ...((p?.offers && [].concat(p.offers).map(o => o?.name)) || [])];
    let conc = '';
    let intense = false;   // "Eau de Toilette Intense": sometimes its own version (Gucci Guilty), see score()
    for (const s of concSources) {
      const t = withoutBrand(trimDescription(s || ''), brand);
      conc = FN.detectConc(t);
      if (conc) { intense = /\beau de (parfum|toilette) intense\b/i.test(t); break; }
    }

    // Gift sets ("Stronger With You Geschenkset"): the set's own name often says little ("Armani Set"), so the
    // perfume is taken from the list of what's in it ("EMPORIO STRONGER WYO EDP SPRAY (50.0 ml)"), skipping the
    // shower gel and samples. Without such a line there is no automatic lookup. Set pages never share prices or
    // facts (see isSet below): a set price isn't the price of the bottle.
    const isSet = SET_RE.test(`${name} ${h1Text} ${document.title}`);
    if (isSet) {
      const item = setPerfume();
      if (item) {
        conc = FN.detectConc(item) || conc;
        cleaned = cleanName(expandAbbr(item), brand).replace(new RegExp(`^(${escRe(brand)}\\s+)`, 'i'), '');
      } else {
        cleaned = '';
      }
    }

    // Also look at the size options and breadcrumbs ("Parfum › Herrendüfte") for the word "perfume".
    const offerNames = (p?.offers && [].concat(p.offers).map(o => o?.name || '').join(' ')) || '';
    // Only the outermost breadcrumb elements: on some shops the first match is a single "Home" item.
    // The text pieces are joined with spaces: textContent glues the items together on shops like Douglas
    // ("ParfumHerenparfum"), and then "Heren" is no longer a word of its own.
    const crumbEls = [...document.querySelectorAll('nav[aria-label*="breadcrumb" i], [class*="breadcrumb" i], [itemtype$="BreadcrumbList"]')];
    const spacedText = el => {
      const parts = [], walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      while (walk.nextNode()) { const t = walk.currentNode.nodeValue.trim(); if (t) parts.push(t); }
      return parts.join(' ');
    };
    const crumbs = crumbEls.filter(e => !crumbEls.some(o => o !== e && o.contains(e)))
      .slice(0, 2).map(spacedText).join(' ').slice(0, 400);
    const path = decodeURIComponent(location.pathname).replace(/[-_/.]+/g, ' ');   // e.g. "/en/fruity-perfumes/…"
    const blob = `${brand} ${candidates.join(' ')} ${p?.category || ''} ${offerNames} ${crumbs} ${path} ${document.title}`;
    // Only real product pages count (not the homepage or category pages).
    const isProduct = !!p || !!document.querySelector('meta[property="og:type"][content*="product" i]');
    // Other products of a perfume line ("Boss Bottled Deodorant Spray", "Sauvage Shower Gel") are not the perfume:
    // no panel, and nothing is shared from them (their price is not the perfume's price).
    const isFragrance = !!name && !!cleaned && FRAG_RE.test(blob) && !NOT_FRAG_RE.test(`${name} ${h1Text} ${document.title}`);
    // Keep "Pour Homme" / "Pour Femme" from the name: cleanName drops them, but they tell versions apart
    // (Gucci Guilty Pour Homme vs the women's Gucci Guilty). Only the explicit phrase, not descriptions.
    const gText = ` ${name} ${h1Text} `.toLowerCase();
    const gender = /\b(pour homme|for men|for him)\b/.test(gText) ? 'Pour Homme'
      : /\b(pour femme|for women|for her)\b/.test(gText) ? 'Pour Femme' : '';
    return {
      query: [brand, cleaned, gender, FN.CONC_PHRASE[conc] || '', intense && (conc === 'edp' || conc === 'edt') ? 'Intense' : '']
        .filter(Boolean).join(' ').trim(),
      brand, name: cleaned, product: p, crumbs,
      conc,
      isSet,
      isProduct,
      isFragrance,
      show: isProduct && isFragrance
    };
  }

  // ---------- product facts (opt-in: "Help build the open perfume database") ----------
  // Facts a shop shows about the perfume on its product page: barcode, the notes it lists, the fragrance
  // family and who it's for. Only sent when the user turned that setting on (see background.js).
  const NOTE_LABELS = {
    // Dutch: topnoot/topnoten/topnote(s) (Notino: "Topnoten", "Hartnoten", "Basisnoten"), also with a space.
    top: /^(top ?notes?|head notes?|(top|kop) ?no(ot|ten?|tes)|kopfnoten?|note(s)? de t[êe]te|notas? de salida|notas? altas|notas? de topo|notas? de sa[ií]da|note di testa|nuty g[łl]owy|nuty g[óo]rne)$/i,
    heart: /^(heart notes?|middle notes?|hart ?no(ot|ten?|tes)|herznoten?|note(s)? de c(œ|oe)ur|notas? de coraz[óo]n|notas? de cora[çc][ãa]o|note di cuore|nuty serca)$/i,
    base: /^(base notes?|basis ?no(ot|ten?|tes)|note(s)? de fond|notas? de fondo|notas? de base|notas? de fundo|note di fondo|note di base|nuty bazy|nuty g[łl][ęe]bi)$/i,
    family: /^(fragrance famil(y|ies)|olfactory famil(y|ies)|scent famil(y|ies)|geurfamilie|geursoort|geurnoot|duftfamilie|duftnote|duftrichtung|famille olfactive|familia olfativa|famiglia olfattiva|fam[ií]lia olfativa|rodzina zapach[óo]w|rodzina zapachowa|nuta zapachowa)$/i
  };
  // Separators: commas, semicolons, slashes, "&", "+", " - " ("Zwarte Peper - Mandarijn - Bergamot") and "and".
  // "Ceder- Amberhout" (parfumwebshop.nl) is two notes too.
  const splitNotes = v => String(v || '').split(/\s*(?:,|;|\/|\s&\s|\s\+\s|\s[-–]\s|(?<=\w)-\s|\s(?:and|en|und|et|y|e|i|и)\s)\s*/i)
    .map(x => x.replace(/^[\s\-–•·.:]+|[\s.]+$/g, '').trim())
    .filter(x => x.length >= 2 && x.length <= 40 && !/\d{3,}/.test(x)).slice(0, 15);
  function readNotes() {
    const found = {};
    const els = document.querySelectorAll('dt, th, td, span, div, strong, b, p, li, h3, h4, h5, label');
    for (const el of els) {
      if (el.closest('[data-fn-host]') || el.closest(OTHER_PRODUCTS_SEL)) continue;
      const own = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!own || own.length > 400) continue;
      // "Label: value" in one element, or a label element followed by its value.
      const m = own.match(/^([^:]{3,32}):\s*(.+)$/);
      const label = (m ? m[1] : own).replace(/:$/, '').trim();   // "Top noten:" (Parfumwebshop) is a label too
      for (const [k, re] of Object.entries(NOTE_LABELS)) {
        if (found[k] || !re.test(label)) continue;
        let value = m ? m[2] : '';
        if (!value && own.length <= 32) {
          // The value is the next element; when the label sits alone in a wrapper (<th><span>Topnoten</span></th>),
          // it's the wrapper's next element.
          let src = el;
          for (let i = 0; i < 3 && !src.nextElementSibling && src.parentElement && src.parentElement.textContent.trim() === src.textContent.trim(); i++) src = src.parentElement;
          value = (src.nextElementSibling?.textContent || '').replace(/\s+/g, ' ').trim();
        }
        // An empty box followed by the next box's label ("Geurfamilie" then "SUBFAMILIE" on Parfumerie.nl) is no value.
        if (Object.values(NOTE_LABELS).some(re => re.test(value)) || /^(sub ?)?famil(y|ie|le|ia)\b/i.test(value)) value = '';
        // parfumwebshop.nl puts all tiers in one line under "Top noten": stop at the next tier's label.
        value = value.split(/\s(?:top|kop|hoofd|hart|basis|heart|middle|base)\s?(?:noten|notes|noot|note)\s*:/i)[0];
        const list = value && value.length <= 300 ? splitNotes(value) : [];
        // A story instead of a list ("Topnoten: De geur opent met de citrusachtige, houtachtige …"): not notes. A
        // later list on the page (Parfumwebshop has both) still counts.
        if (list.some(x => x.split(/\s+/).length > 4)) continue;
        if (list.length) found[k] = list;
      }
      if (found.top && found.heart && found.base && found.family) break;
    }
    // No notes table on this page: try the description text (textNotes, below).
    if (!found.top && !found.heart && !found.base) Object.assign(found, textNotes());
    return found;
  }
  // ---------- notes in running text ----------
  // Shops without a notes table often write them in the description: "het kruidige akkoord van de topnoten: een mix
  // van kardemom, roze peperkorrel en vioolblaadjes" (Kruidvat), "De basisnoten zijn subtieler met warme zoete
  // vanille, gember en … kastanje" (Parfumerie.nl). Only sentences that say which level they describe are read, and
  // from those only known note words (KNOWN_NOTES), so adjectives ("warme zoete") and ingredient lists stay out.
  // NOTE_GROUPS (spelling > the note's English name) is generated from NOTE_WORDS in server/catalog.py, without
  // fragrance families such as "zoet", "fris" or "hout" (adjectives in running text); regenerate it when that table
  // grows. It's also how the panel recognises a Fragrantica note as one the database confirmed (see ownChecks).
  const NOTE_GROUPS = new Map('schwarze johannisbeere>blackcurrant|artemisia dracunculus>tarragon|frutto della passione>passion fruit|geglazuurde kastanjes>glazed chestnut|feuilles de violette>violet leaf|geglazuurde kastanje>glazed chestnut|bittere sinaasappel>bitter orange|feuille de violette>violet leaf|fruit de la passion>passion fruit|lirio de los valles>lily of the valley|chiodi di garofano>clove|foglia di violetta>violet leaf|fruta de la pasion>passion fruit|kandierte kastanie>glazed chestnut|lelietje van dalen>lily of the valley|lily of the valley|mandarine sanguine>blood mandarin|muschio di quercia>oakmoss|baies de genievre>juniper|bois de cachemire>cashmeran|graine d ambrette>ambrette|muskatellersalbei>clary sage|roze peperkorrels>pink pepper|schwarzer pfeffer>black pepper|viooltjesbladeren>violet leaf|bloedsinaasappel>blood orange|castagna candita>glazed chestnut|frangipane bloem>frangipani|glazed chestnuts>glazed chestnut|naranja sanguina>blood orange|pink peppercorns>pink pepper|roze peperkorrel>pink pepper|sciroppo d acero>maple syrup|vainilla bourbon>bourbon vanilla|verbena de limon>lemon verbena|almizcle blanco>white musk|anis estrellado>star anise|bloed mandarijn>blood mandarin|bourbon vanilla|bourbon vanille>bourbon vanilla|cistus labdanum>labdanum|clou de girofle>clove|fiore d arancio>orange blossom|fiori d arancio>orange blossom|fleur d oranger>orange blossom|glazed chestnut|hoja de violeta>violet leaf|juniper berries>juniper|mousse de chene>oakmoss|neroli bigarade>neroli|noix de muscade>nutmeg|orange sanguine>blood orange|pink peppercorn>pink pepper|vanilla bourbon>bourbon vanilla|vanille bourbon>bourbon vanilla|veilchenblatter>violet leaf|weisser moschus>white musk|zitronenverbene>lemon verbena|anice stellato>star anise|bloedmandarijn>blood mandarin|blood mandarin|bois de santal>sandalwood|bourbonvanille>bourbon vanilla|citroenverbena>lemon verbena|grosella negra>blackcurrant|jarabe de arce>maple syrup|marrons glaces>glazed chestnut|muschio bianco>white musk|musgo de roble>oakmoss|naranja amarga>bitter orange|orange blossom|oranje bloesem>orange blossom|orchidee noire>orchid|passionsfrucht>passion fruit|pimienta negra>black pepper|salvia sclarea>clary sage|sirop d erable>maple syrup|wacholderbeere>juniper|alpenveilchen>cyclamen|ambrette seed>ambrette|arancia amara>bitter orange|arancia rossa>blood orange|bitter orange|black currant>blackcurrant|bois de cedre>cedar|bois de gaiac>guaiac wood|cashmere wood>cashmeran|chevrefeuille>honeysuckle|dennennaalden>pine|encens oliban>frankincense|feve de tonka>tonka bean|fruits rouges>red berries|jeneverbessen>juniper|jeneverstruik>juniper|juniper berry>juniper|lemon verbena|orangenbluete>orange blossom|oranjebloesem>orange blossom|passion fruit|pimienta rosa>pink pepper|racine d iris>iris|rode vruchten>red berries|sauge sclaree>clary sage|sour cherries>sour cherry|veilchenblatt>violet leaf|violet leaves>violet leaf|vioolblaadjes>violet leaf|viooltjesblad>violet leaf|weihrauchharz>frankincense|zonnige noten>solar notes|zwarte bessen>blackcurrant|ambra grigia>ambergris|ambrettezaad>ambrette|bitterorange>bitter orange|black pepper|blackcurrant|blood orange|bois de rose>rosewood|frangipanier>frangipani|frankincense|frutos rojos>red berries|frutti rossi>red berries|granaatappel>pomegranate|grijze amber>ambergris|hierba limon>lemongrass|iris pallida>iris|kamperfoelie>honeysuckle|karamelsnoep>toffee|kaschmirholz>cashmeran|kasjmierhout>cashmeran|maiglockchen>lily of the valley|marron glace>glazed chestnut|mela cotogna>quince|muskaatsalie>clary sage|noce moscata>nutmeg|noix de coco>coconut|nuez moscada>nutmeg|orange amere>bitter orange|orangenblute>orange blossom|pamplemousse>grapefruit|passievrucht>passion fruit|peperkorrels>pepper|pine needles>pine|pistachenoot>pistachio|rosa pfeffer>pink pepper|sauerkirsche>sour cherry|witte muskus>white musk|zitronengras>lemongrass|zwarte peper>black pepper|ahornsiroop>maple syrup|albaricoque>apricot|baies roses>pink pepper|bois ambres>amberwood|caprifoglio>honeysuckle|citroengras>lemongrass|citron vert>lime|citronnelle>lemongrass|dennennaald>pine|dragoncello>tarragon|gewurznelke>clove|granatapfel>pomegranate|guaiac hout>guaiac wood|guaiac wood|honeysuckle|ilang ilang>ylang ylang|iso e super|kreuzkummel>cumin|kruidnagels>clove|laurierblad>bay leaf|mahoniehout>mahogany|maple syrup|marshmallow|mineralisch>mineral|nootmuskaat>nutmeg|oranjebloem>orange blossom|orriswortel>iris|palissander>rosewood|peperkorrel>pepper|peppercorns>pepper|petit grain>petitgrain|pfingstrose>peony|pink pepper|poivre noir>black pepper|poivre rose>pink pepper|pomegranate|red berries|rode bessen>red berries|rosa pepper>pink pepper|rote beeren>red berries|sinaasappel>orange|solar notes|sour cherry|sparrenhout>fir|tonka beans>tonka bean|tonka bohne>tonka bean|violet leaf|ylang ylang|zure kersen>sour cherry|ahornsirup>maple syrup|ambar gris>ambergris|amber gris>ambergris|amber wood>amberwood|ambre gris>ambergris|balsam fir>fir|bergamotte>bergamot|bergamotto>bergamot|berkenhout>birch|berkenteer>birch|blackberry|blutorange>blood orange|bois ambre>amberwood|bois d oud>oud|cioccolato>chocolate|clary sage|clementina>clementine|clementine|coriandolo>coriander|eichenmoos>oakmoss|fava tonka>tonka bean|feve tonka>tonka bean|frangipani|geissblatt>honeysuckle|grapefruit|guaiachout>guaiac wood|guajakholz>guaiac wood|haba tonka>tonka bean|hazelnoten>hazelnut|heliotroop>heliotrope|heliotrope|heliotropo>heliotrope|iriswortel>iris|iriswurzel>iris|jeneverbes>juniper|karwijzaad>caraway|kruidnagel>clove|lemongrass|liquirizia>licorice|lotusbloem>lotus|lotusblume>lotus|madreselva>honeysuckle|mintachtig>mint|monoi olie>monoi|musc blanc>white musk|muskatnuss>nutmeg|muskuszaad>ambrette|neroli oil>neroli|neroliolie>neroli|olive tree|olivenbaum>olive tree|orchideeen>orchid|orris root>iris|palisandro>rosewood|peppercorn>pepper|petitgrain|pioenrozen>peony|pistacchio>pistachio|pompelmoes>grapefruit|red fruits>red berries|ribes nero>blackcurrant|roze peper>pink pepper|rozemarijn>rosemary|sandalwood|sandelholz>sandalwood|sandelhout>sandalwood|schokolade>chocolate|star anise|strawberry|tonka bean|tonka boon>tonka bean|tonkabohne>tonka bean|tonkabonen>tonka bean|vijgenblad>fig|water lily|waterlelie>water lily|white musk|witte musk>white musk|ylangylang>ylang ylang|zedernholz>cedar|zonnenoten>solar notes|zwarte bes>blackcurrant|aardbeien>strawberry|abrikozen>apricot|adlerholz>oud|albicocca>apricot|alcaravea>caraway|aldehyden>aldehydes|aldehydes|ambergris|amberhout>amberwood|amberwood|ambroxide>ambroxan|basilicum>basil|basilikum>basil|bergamota>bergamot|bevergeil>castoreum|birch tar>birch|brombeere>blackberry|caramello>caramel|cardamome>cardamom|cardamomo>cardamom|carnation|cashmeran|castoreum|cedarwood>cedar|cederhout>cedar|champagne|chataigne>chestnut|chestnuts>chestnut|chocolade>chocolate|chocolate|concombre>cucumber|coriander|coriandre>coriander|ebbenhout>ebony|eikenhout>oak|framboise>raspberry|frambozen>raspberry|frambuesa>raspberry|gelsomino>jasmine|giaggiolo>iris|gingembre>ginger|haselnuss>hazelnut|hazelnoot>hazelnut|heliotrop>heliotrope|hyazinthe>hyacinth|irisbloem>iris|kastanien>chestnut|kastanjes>chestnut|kokosnoot>coconut|kokosnuss>coconut|komkommer>cucumber|koriander>coriander|liquorice>licorice|mandarijn>mandarin|mandarina>mandarin|mandarine>mandarin|mandarino>mandarin|melocoton>peach|melograno>pomegranate|membrillo>quince|monoi oil>monoi|narcissen>narcissus|narcissus|nectarina>nectarine|nectarine|nektarine>nectarine|olijfboom>olive tree|olijfhout>olive tree|osmanthus|ozonische>ozonic|patchoeli>patchouli|patchouli|patchouly>patchouli|pepe nero>black pepper|pepe rosa>pink pepper|pineapple|pioenroos>peony|pistachio|rabarbaro>rhubarb|raspberry|rhabarber>rhubarb|rosenholz>rosewood|rosmarino>rosemary|rozenhout>rosewood|sea notes>marine|steranijs>star anise|sternanis>star anise|tonkaboon>tonka bean|tubereuse>tuberose|vioolblad>violet leaf|viooltjes>violet|wacholder>juniper|weihrauch>incense|wildleder>suede|zafferano>saffron|zure kers>sour cherry|abrikoos>apricot|absinthe>wormwood|agarwood>oud|albahaca>basil|aldehyde>aldehydes|almendra>almond|almizcle>musk|ambrette|ambrofix>ambroxan|ambroxan|aprikose>apricot|assenzio>wormwood|avellana>hazelnut|basilico>basil|baunilha>vanilla|bay leaf|benzoine>benzoin|benzoino>benzoin|bergamot|bigarade>bitter orange|camoscio>suede|cannella>cinnamon|cannelle>cinnamon|caramelo>caramel|cardamom|castagna>chestnut|cetriolo>cucumber|champaca|cherries>cherry|chestnut|chocolat>chocolate|cilantro>coriander|ciliegia>cherry|cinnamon|cipresso>cypress|cistrose>labdanum|cucumber|cyclamen|ebbehout>ebony|ebenholz>ebony|eikenmos>oakmoss|erdbeere>strawberry|estragon>tarragon|fig leaf>fig|framboos>raspberry|galbanum|gardenia|gardenie>gardenia|garofano>carnation|genievre>juniper|geranium|giacinto>hyacinth|guimauve>marshmallow|hazelnut|himbeere>raspberry|hyacinth|incienso>incense|jacinthe>hyacinth|jengibre>ginger|karamell>caramel|kardamom>cardamom|kardemom>cardamom|kastanie>chestnut|kastanje>chestnut|kirschen>cherry|kweepeer>quince|labdanum|lavendel>lavender|lavender|licorice|limoenen>lime|magnolia|magnolie>magnolia|mahagoni>mahogany|mahogany|mandarin|mandorla>almond|maracuja>passion fruit|maritime>marine|mineraal>mineral|minerale>mineral|mineraux>mineral|mughetto>lily of the valley|narcisse>narcissus|narzisse>narcissus|nenuphar>water lily|nocciola>hazelnut|noisette>hazelnut|oak moss>oakmoss|olibanum>frankincense|orchidea>orchid|orchidee>orchid|orquidea>orchid|osmanthe>osmanthus|ozonisch>ozonic|pfirsich>peach|pimienta>pepper|pistache>pistachio|pistacho>pistachio|pistazie>pistachio|plumeria>frangipani|pompelmo>grapefruit|pralinee>praline|pralines>praline|rabarber>rhubarb|reglisse>licorice|rhubarbe>rhubarb|rosemary|rosewood|rosmarin>rosemary|ruibarbo>rhubarb|saffraan>saffron|scharlei>clary sage|sea salt>salt|seringen>lilac|slagroom>cream|tarragon|tuberoos>tuberose|tuberosa>tuberose|tuberose|vainilla>vanilla|vaniglia>vanilla|veilchen>violet|verveine>lemon verbena|vetivert>vetiver|violetta>violet|violette>violet|viooltje>violet|wormwood|zibetone>civet|zoethout>licorice|zucchero>sugar|zypresse>cypress|aardbei>strawberry|abricot>apricot|aldeidi>aldehydes|amandel>almond|amarena>sour cherry|apricot|arancia>orange|azafran>saffron|badiane>star anise|basilic>basil|benjoin>benzoin|benzoin|betulla>birch|bouleau>birch|caramel|caraway|castana>chestnut|champak>champaca|ciruela>plum|citroen>lemon|civette>civet|coconut|cyclaam>cyclamen|cypress|flieder>lilac|fragola>strawberry|freesia|freesie>freesia|geranie>geranium|geranio>geranium|ginepro>juniper|granada>pomegranate|grenade>pomegranate|griotte>sour cherry|guaiaco>guaiac wood|guayaco>guaiac wood|hedione|hyacint>hyacinth|incense|incenso>incense|irissen>iris|jacinto>hyacinth|jasmijn>jasmine|jasmine|jenever>juniper|juniper|karamel>caramel|kaviaar>caviar|kirsche>cherry|ladanum>labdanum|lakritz>licorice|lampone>raspberry|laurier>bay leaf|lavanda>lavender|lavande>lavender|leather|limetta>lime|limette>lime|lorbeer>bay leaf|lychees>lychee|mahonie>mahogany|manzana>apple|mariene>marine|mineral|moschus>musk|muschio>musk|naranja>orange|narciso>narcissus|oakmoss|oakwood>oak|oeillet>carnation|olivier>olive tree|osmanto>osmanthus|oudhout>oud|pachuli>patchouli|papyrus|peonies>peony|pfeffer>pepper|pflaume>plum|pimenta>pepper|pivoine>peony|praline|pruimen>plum|quercia>oak|regaliz>licorice|rhubarb|rokerig>smoke|romarin>rosemary|saffron|sandalo>sandalwood|seerose>water lily|solaire>solar notes|spekjes>marshmallow|tabacco>tobacco|thymian>thyme|tobacco|tomillo>thyme|vanilla|vanille>vanilla|verbena>lemon verbena|vetiver|vetyver>vetiver|violeta>violet|wanilia>vanilla|whiskey|wierook>incense|zeegeur>marine|zeezout>salt|zenzero>ginger|zitrone>lemon|abedul>birch|absint>wormwood|acajou>mahogany|ajenjo>wormwood|alloro>bay leaf|almond|amande>almond|ambrox>ambroxan|ananas>pineapple|anjers>carnation|azahar>orange blossom|azucar>sugar|banaan>banana|banana|banane>banana|benjui>benzoin|benzoe>benzoin|bramen>blackberry|brandy>cognac|canela>cinnamon|cassis>blackcurrant|caviar|cereza>cherry|cerise>cherry|cherry|cipres>cypress|cistus>labdanum|citron>lemon|clavel>carnation|cloves>clove|coffee|cognac|comino>cumin|cypres>cypress|davana|dennen>pine|dragon>tarragon|encens>incense|enebro>juniper|fraise>strawberry|fresia>freesia|gamuza>suede|gember>ginger|giglio>lily|ginger|guinda>sour cherry|harsen>resin|hierba>grass|honing>honey|ingwer>ginger|jasmin>jasmine|jazmin>jasmine|kaffee>coffee|kaneel>cinnamon|karwij>caraway|kaviar>caviar|kersen>cherry|kiefer>pine|koffie>coffee|komijn>cumin|kummel>caraway|laurel>bay leaf|lelies>lily|lilies>lily|limoen>lime|limone>lemon|litchi>lychee|lychee|mandel>almond|mangue>mango|marino>marine|marron>chestnut|meloen>melon|melone>melon|menthe>mint|mimosa|mimose>mimosa|mogano>mahogany|mousse>moss|muguet>lily of the valley|muskus>musk|myrrhe>myrrh|narcis>narcissus|neroli|ninfea>water lily|nutmeg|orange|orchid|ozonic|papiro>papyrus|peonia>peony|pepino>cucumber|pepper|perzik>peach|poivre>pepper|pomelo>grapefruit|prugna>plum|quince|quitte>quince|resina>resin|resine>resin|resins>resin|romero>rosemary|safran>saffron|salbei>sage|salvia>sage|santal>sandalwood|sering>lilac|spekje>marshmallow|suiker>sugar|tabaco>tobacco|toffee|vijgen>fig|violet|wermut>wormwood|whisky>whiskey|zucker>sugar|abete>fir|abeto>fir|alsem>wormwood|ambar>amber|amber|ambra>amber|ambre>amber|anice>anise|anijs>anise|anise|anjer>carnation|apfel>apple|appel>apple|apple|basil|birch|birke>birch|birne>pear|braam>blackberry|cacao>cocoa|caffe>coffee|caoba>mahogany|carvi>caraway|cedar|ceder>cedar|cedre>cedar|cedro>cedar|chene>oak|ciste>labdanum|civet|clavo>clove|clove|cocco>coconut|cocoa|cream|crema>cream|creme>cream|cuero>leather|cumin|cuoio>leather|ebano>ebony|ebene>ebony|ebony|eiche>oak|elemi|feige>fig|fieno>hay|figue>fig|fresa>strawberry|fumee>smoke|gaiac>guaiac wood|grass|gurke>cucumber|herbe>grass|honey|honig>honey|kakao>cocoa|kokos>coconut|latte>milk|leche>milk|leder>leather|lelie>lily|lemon|lilac|lilas>lilac|lilie>lily|limon>lemon|lotus|mango|marin>marine|melon|menta>mint|miele>honey|milch>milk|minty>mint|minze>mint|mirra>myrrh|mirre>myrrh|monoi|musgo>moss|myrrh|nelke>clove|olijf>olive tree|olive>olive tree|olivo>olive tree|orris>iris|ozone>ozonic|ozono>ozonic|panna>cream|peach|peche>peach|peony|peper>pepper|pesca>peach|pioen>peony|plums>plum|poire>pear|pomme>apple|pruim>plum|prune>plum|rauch>smoke|resin|roble>oak|rosen>rose|roses>rose|rozen>rose|sahne>cream|salie>sage|sapin>fir|sauge>sage|smoke|solar>solar notes|sonne>solar notes|suede|sugar|tabac>tobacco|tabak>tobacco|tanne>fir|thyme|tiare>monoi|tonka>tonka bean|ylang>ylang ylang|zeder>cedar|zibet>civet|anis>anise|berk>birch|cafe>coffee|coco>coconut|cuir>leather|daim>suede|drop>licorice|erba>grass|fico>fig|foin>hay|fumo>smoke|gras>grass|hars>resin|harz>resin|heno>hay|higo>fig|hooi>hay|humo>smoke|iris|kers>cherry|kwee>quince|lait>milk|leer>leather|lila>lilac|lily|lima>lime|lime|loto>lotus|meer>marine|mela>apple|melk>milk|miel>honey|milk|mint|moos>moss|mora>blackberry|moss|munt>mint|mure>blackberry|musc>musk|musk|oudh>oud|ozon>ozonic|pear|peer>pear|pepe>pepper|pera>pear|pina>pineapple|pine|pino>pine|plum|rhum>rum|rook>smoke|room>cream|roos>rose|rosa>rose|rose|sage|sale>salt|salt|salz>salt|spar>fir|thee>tea|thym>thyme|tijm>thyme|timo>thyme|vijg>fig|vino>wine|wein>wine|wijn>wine|wine|yuzu|zimt>cinnamon|zout>salt|den>pine|eik>oak|fig|fir|hay|heu>hay|lis>lily|lys>lily|mos>moss|oak|oud|pin>pine|ron>rum|rum|sal>salt|sea>marine|sel>salt|tea|tee>tea|the>tea|vin>wine|zee>marine|zon>solar notes|te>tea'.split('|').map(x => { const [v, c] = x.split('>'); return [v, c || v]; }));
  const KNOWN_NOTES = [...NOTE_GROUPS.keys()];   // longest first
  const plainText = s => String(s || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const TIER_CUES = [
    ['top', /\b(?:top|kop|hoofd)\s?no(?:ot|ten|te|tes)\b|\btop notes?\b|\bhead notes?\b|\bopening\b|\bopent\b|\bopens\b|\beerste\b|\bfirst\b|\bbegint\b|\bkopfnoten?\b|\bnotes? de tete\b|\bnotas? de salida\b|\bnote di testa\b/],
    ['heart', /\bhart\s?no(?:ot|ten|te|tes)\b|\bheart\b|\bhart\b|\bmidden\b|\bmiddle\b|\bherznoten?\b|\bnotes? de c(?:oe|œ)?ur\b|\bnotas? de corazon\b|\bnote di cuore\b/],
    ['base', /\bbasis\s?no(?:ot|ten|te|tes)\b|\bbase notes?\b|\bdroogt\b|\bdry ?down\b|\bonderlaag\b|\bbasisnoten?\b|\bnotes? de fond\b|\bnotas? de fondo\b|\bnote di fondo\b/]
  ];
  const knownIn = p => {
    let s = ` ${p} `;
    const hits = [];
    for (const w of KNOWN_NOTES) {
      let i;
      while ((i = s.indexOf(` ${w} `)) !== -1) {
        hits.push([i, w]);
        s = s.slice(0, i + 1) + ' '.repeat(w.length) + s.slice(i + 1 + w.length);   // a word is used once
      }
    }
    return hits.sort((a, b) => a[0] - b[0]).map(([, w]) => w.charAt(0).toUpperCase() + w.slice(1));
  };
  function textNotes() {
    const found = {};
    const blocks = [...document.querySelectorAll('p, li, div, section, article, span, dd, td')].filter(el => {
      const n = (el.textContent || '').length;
      return n >= 40 && n <= 3000 && ![...el.children].some(c => (c.textContent || '').length >= 40) &&
        !el.closest('[data-fn-host]') && !el.closest(OTHER_PRODUCTS_SEL) && !el.closest('[class*="review" i],[id*="review" i]');
    });
    for (const el of blocks.slice(0, 200)) {
      for (const sentence of (el.textContent || '').split(/(?<=[.!?])\s+|\n+/)) {
        const p = plainText(sentence);
        let tier = null, at = Infinity;
        for (const [k, re] of TIER_CUES) { const m = p.match(re); if (m && m.index < at) { tier = k; at = m.index; } }
        if (!tier) continue;
        const list = found[tier] || (found[tier] = []);
        for (const n of knownIn(p)) if (!list.includes(n) && list.length < 15) list.push(n);
      }
    }
    for (const k of Object.keys(found)) if (!found[k].length) delete found[k];
    const total = Object.values(found).reduce((s, l) => s + l.length, 0);
    return total >= 2 ? found : {};
  }
  // On a brand's own website (FN.officialSite) the product text names the official notes, often without a pyramid
  // ("the signature chestnut accord with a spicy and warm leathered vanilla", armani.com). Every known note word in
  // the product text, in order, without a tier; the server counts them as confirmed for that brand's perfumes only.
  // Ingredient lists ("Ingredients: alcohol, aqua, parfum, linalool…") and other products' tiles are skipped.
  // Note words that are also everyday words in a running text ("the" is French thé, "room" Dutch cream, "drop"
  // Dutch licorice, "peer" Dutch pear): fine in a shop's note list, not in a story. The server skips them too.
  const PROSE_NOISE = new Set(['the', 'te', 'tee', 'den', 'pin', 'room', 'drop', 'peer', 'rook', 'sale', 'sal', 'sel', 'vin',
    'zee', 'zon', 'sea', 'meer', 'lis', 'lys', 'heu', 'eik', 'mos', 'hars', 'gras', 'erba', 'fico', 'foin', 'humo', 'fumo',
    'lima', 'mora', 'pera', 'mela', 'kers', 'spar', 'loto', 'creme', 'cream', 'solar', 'sonne', 'marin', 'resin']);
  function mentionedNotes() {
    if (!FN.officialSite(location.hostname)) return [];
    const root = document.querySelector('main') || document.body;
    const out = [];
    for (const el of root.querySelectorAll('p, li, div, section, article, span, dd, td')) {
      const n = (el.textContent || '').length;
      if (n < 30 || n > 3000 || [...el.children].some(c => (c.textContent || '').length >= 30)) continue;
      if (el.closest('[data-fn-host]') || el.closest(OTHER_PRODUCTS_SEL) || el.closest('[class*="review" i],[id*="review" i]')) continue;
      const text = plainText(el.textContent);
      if (/\b(ingredients?|ingredienten|ingrediënten|inhaltsstoffe|ingredientes|ingredienti|skladniki|inci|alcohol denat|linalool)\b/.test(text)) continue;
      for (const w of knownIn(text)) if (!PROSE_NOISE.has(w.toLowerCase()) && !out.includes(w) && out.length < 20) out.push(w);
    }
    return out;
  }
  // Barcodes (GTIN/EAN) from the shop's product data, only when the check digit is right.
  const validGtin = g => {
    if (!/^\d{8}$|^\d{12,14}$/.test(g)) return false;
    const d = g.split('').map(Number), check = d.pop();
    const sum = d.reverse().reduce((s, x, i) => s + x * (i % 2 === 0 ? 3 : 1), 0);
    return (10 - (sum % 10)) % 10 === check;
  };
  function readGtins(p) {
    const out = new Set();
    const take = o => ['gtin13', 'gtin', 'gtin12', 'gtin14', 'gtin8', 'ean'].forEach(k => {
      const v = String(o?.[k] ?? '').replace(/\D/g, '');
      if (validGtin(v)) out.add(v.padStart(13, '0').slice(-13));
    });
    take(p);
    [].concat(p?.offers || []).forEach(o => { take(o); [].concat(o?.offers || []).forEach(take); });
    [].concat(p?.hasVariant || []).forEach(take);
    document.querySelectorAll('[itemprop^="gtin"]').forEach(el => take({ gtin: el.getAttribute('content') || el.textContent }));
    return [...out].slice(0, 8);
  }
  const genderOf = t => {
    t = ' ' + String(t || '').toLowerCase() + ' ';
    if (/\bunisex\b/.test(t)) return 'u';
    if (/\b(pour femme|for women|for her|dames|damen|vrouwen|femme|women|donna|mujer|damsk|kobiet|femin)/.test(t)) return 'f';
    if (/\b(pour homme|for men|for him|heren|herren|mannen|homme|men|uomo|hombre|m[eę]sk|mascul)/.test(t)) return 'm';
    return '';
  };
  // Breadcrumb names from the shop's product data (Notino: "Parfums › Heren parfums"), for the gender.
  function ldCrumbs() {
    const names = [];
    const walk = o => {
      if (!o || typeof o !== 'object' || names.length > 20) return;
      if (Array.isArray(o)) return o.forEach(walk);
      if (Array.isArray(o.itemListElement) && /BreadcrumbList/i.test([].concat(o['@type'] || '').join(' ')))
        o.itemListElement.forEach(li => { const n = li?.name || li?.item?.name; if (typeof n === 'string') names.push(n); });
      Object.values(o).forEach(walk);
    };
    document.querySelectorAll('script[type="application/ld+json"]').forEach(s => { try { walk(JSON.parse(s.textContent)); } catch {} });
    return names.join(' ').slice(0, 300);
  }
  function readFacts(cur, prices) {
    const notes = readNotes();
    const h1 = document.querySelector('h1')?.textContent || '';
    return {
      brand: String(cur.brand || '').slice(0, 80),
      name: String(cur.name || '').slice(0, 120),
      conc: cur.conc || '',
      gender: genderOf(`${h1} ${cur.crumbs || ''} ${ldCrumbs()}`),
      sizes: [...new Set(prices.map(p => p.ml).filter(ml => ml > 0 && ml <= 1000))].slice(0, 8),
      gtins: readGtins(cur.product),
      notes: { top: notes.top || [], heart: notes.heart || [], base: notes.base || [], mentioned: mentionedNotes() },
      families: notes.family || [],
      lang: (document.documentElement.lang || '').slice(0, 5).toLowerCase()
    };
  }

  // ---------- price per ml ----------
  // Sizes and prices: first from the shop's product data (offers per size), otherwise from the
  // page text, where each size option usually sits in its own element with its price.
  const SIZE_RE = /(\d+(?:[.,]\d+)?)\s?(?:ml|mL|ML)\b/;
  // US shops give sizes in fluid ounces ("1.7 oz", "3.4 fl. oz."). Those are turned into ml first and
  // rounded to the usual bottle size (1.7 oz = 50.3 ml → 50 ml, 3.4 oz → 100 ml, 1 oz → 30 ml).
  const OZ_RE = /(\d+(?:[.,]\d+)?|[.,]\d+)\s?(?:fl\.?\s?)?oz\.?(?![a-z])/gi;
  // US labels state a bottle's ounces rounded down or about exact (50 ml = 1.69 oz, sold as "1.6 oz" or "1.7 oz";
  // 175 ml as "5.8 oz"), so a common bottle size wins when its exact ounces are 0.05 below to 0.15 above the label;
  // otherwise the nearest other real size within 6%, or else just rounded.
  const COMMON_BOTTLES = [5, 10, 15, 20, 30, 50, 75, 90, 100, 125, 150, 175, 200];
  const OTHER_BOTTLES = [7.5, 8, 25, 35, 40, 45, 60, 65, 70, 80, 110, 120, 180, 250];
  const ozToMl = oz => {
    const ml = oz * 29.5735;
    const near = list => list.reduce((a, b) => (Math.abs(b - ml) < Math.abs(a - ml) ? b : a));
    const c = COMMON_BOTTLES.find(b => { const d = b / 29.5735 - oz; return d >= -0.05 && d <= 0.15; });
    if (c) return c;
    const o = near(OTHER_BOTTLES);
    return Math.abs(o - ml) / o <= 0.06 ? o : Math.round(ml);
  };
  const withMl = t => String(t || '').replace(OZ_RE, (m, n) => `${ozToMl(parseFloat(n.replace(',', '.')))} ml`);
  const CUR = '€|£|\\$|EUR|USD|GBP|CHF|zł|PLN|kr|SEK|DKK|NOK|Kč|CZK|lei|RON|Ft|HUF|₺|TRY|₽|RUB|₴|UAH|AUD|CAD|JPY|¥|₩';
  const NUM = `\\d{1,3}(?:[ .,'\\u00a0]\\d{3})*(?:[.,]\\d{1,2})?|\\d+(?:[.,]\\d{1,2})?`;
  const PRICE_RE = new RegExp(`(?:(${CUR})\\s?(${NUM}))|(?:(${NUM})\\s?(${CUR}))`, 'g');
  // Unit prices such as "100 ml / € 51,41", "€ 149,98 / 100 ml" or "2.545,00 € / 1L" — removed before reading sizes.
  const PER = `(?:\\/|per|pro|je|par|za|за|le|la)`;
  const UNIT = `(?:1\\s?)?(?:fl\\.?\\s?)?oz\\.?|(?:1|10|100)\\s?ml|1\\s?(?:l|L|ltr|liter|litre|litro)\\b|(?:l|L|liter|litre|litro)\\b`;
  const UNIT_PRICE_RE = new RegExp(
    `(?:(?:${CUR})\\s?(?:${NUM})|(?:${NUM})\\s?(?:${CUR}))\\s?${PER}\\s?(?:${UNIT})` +   // price / unit
    `|(?:${UNIT})\\s?(?:${PER}|=|:)\\s?(?:(?:${CUR})\\s?(?:${NUM})|(?:${NUM})\\s?(?:${CUR}))`, 'gi'); // unit / price
  // Prices without a currency sign: after a price word, or else a number with cents that isn't a size.
  const BARE_PRICE_RE = /(?:prijs|price|preis|prix|precio|prezzo|pre[çc]o|cena|pris|hinta|fiyat|цена|nu|now|jetzt|nur|ab|vanaf|from|d[èe]s|desde|da|a partir de)\s?:?\s?(\d{1,4}(?:[.,]\d{2})?)(?!\s?(?:ml|%|g|oz|l)\b)(?![\d.,])/gi;
  const DECIMAL_RE = /(?<![\d.,-])(\d{1,4}[.,]\d{2})(?![\d.,])(?!\s?(?:ml|%|g|oz|l|x)\b)/gi;
  const CUR_CODE = { '€': 'EUR', '£': 'GBP', '$': 'USD', 'zł': 'PLN', 'kr': 'SEK', 'Kč': 'CZK', 'lei': 'RON', 'Ft': 'HUF', '₺': 'TRY', '₽': 'RUB', '₴': 'UAH', '¥': 'JPY', '₩': 'KRW' };
  const toNum = s => {
    s = String(s).replace(/[ ' ]/g, '');
    const last = Math.max(s.lastIndexOf(','), s.lastIndexOf('.'));
    if (last >= 0 && s.length - last - 1 <= 2) return parseFloat(s.slice(0, last).replace(/[.,]/g, '') + '.' + s.slice(last + 1));
    return parseFloat(s.replace(/[.,]/g, ''));
  };

  function readPrices() {
    const map = new Map();
    const add = (m, ml, price, currency) => {
      if (!(ml >= 3 && ml <= 1000 && price > 0)) return;   // under 3 ml are samples, not bottles
      const prev = m.get(ml);
      if (!prev || price < prev.price) m.set(ml, { ml, price, currency: currency || 'EUR' });
    };

    // 1) Structured data: one offer per size (Sephora microdata, many JSON-LD shops).
    const structured = new Map();
    try {
      const p = readProduct();
      const offers = [];
      // The size can be in the offer's own size field, its name, or its SKU ("P-12885-EDT-100ml").
      const pushOffers = (o, fallbackName) => [].concat(o || []).forEach(x => x && offers.push({
        ...x, _size: [x.size, x.itemOffered?.size, x.name, x.sku, x.mpn].filter(v => typeof v === 'string').join(' | '), _name: fallbackName }));
      if (p) {
        pushOffers(p.offers, `${p.size || ''} ${p.name || ''}`);
        [].concat(p.hasVariant || []).forEach(v => pushOffers(v.offers, `${v.size || ''} ${v.name || ''}`));
      }
      for (const o of offers) {
        const size = withMl(o._size).match(SIZE_RE) || withMl(o._name).match(SIZE_RE);
        const price = parseFloat(o.price ?? o.lowPrice);
        if (size) add(structured, toNum(size[1]), price, o.priceCurrency);
      }
    } catch {}
    if (structured.size >= 2) return [...structured.values()].sort((a, b) => a.ml - b.ml).slice(0, 8);

    // "151 , 99" (cents in a separate element) → "151,99"
    const INSTALMENTS_RE = new RegExp(`\\b\\d{1,2}\\s?[x×]\\s?(?:(?:${CUR})\\s?(?:${NUM})|(?:${NUM})\\s?(?:${CUR}))|\\b\\d{1,2}\\s+(?:interest[- ]free\\s+)?(?:payments?|installments?|instalments?|termijnen|raten|paiements|mensualit[ée]s)\\s+(?:of|van|von|de|à)\\s+\\S+`, 'gi');
    const textOf = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').replace(INSTALMENTS_RE, ' ').replace(/(\d)\s?([.,])\s?(\d{2})(?!\d)/g, '$1$2$3').replace(UNIT_PRICE_RE, ' ').replace(OZ_RE, (m, n) => `${ozToMl(parseFloat(n.replace(',', '.')))} ml`);
    const OTHER_PRODUCTS = '[class*="related" i],[class*="recommend" i],[class*="productline" i],[class*="carousel" i],[class*="slider" i],[class*="upsell" i],[class*="cross-sell" i],[class*="crosssell" i],[class*="alternative" i],[class*="similar" i],[class*="product-tile" i],[class*="producttile" i],[class*="recently" i],[class*="also-bought" i],[class*="alsobought" i],[class*="gift" i],[class*="productcard" i],[class*="product-card" i],header,footer,nav,aside';

    // 2) Page text.
    try {
      // Some shops (e.g. Deloox) show prices without a currency sign: "onze prijs: 151,99".
      // Those only count outside product cards for other products (related items, carousels).
      const pageCur = [...structured.values()][0]?.currency || document.querySelector('[itemprop="priceCurrency"]')?.getAttribute('content') || 'EUR';
      const here = location.pathname;
      const linksElsewhere = e => [e.closest('a[href]'), ...e.querySelectorAll('a[href]')].some(a => {
        try { return a && new URL(a.href, location.href).pathname !== here; } catch { return false; }
      });
      const barePrices = t => {
        const out = [...t.matchAll(BARE_PRICE_RE)].map(m => toNum(m[1]));
        return out.length ? out : [...t.matchAll(DECIMAL_RE)].map(m => toNum(m[1]));
      };
      // Cards for other perfumes (alternatives, "also bought", carousels) never count, with or without a
      // currency sign: an element inside such a block, or one that links to another page and has a picture.
      const otherProduct = e => !!e.closest(OTHER_PRODUCTS) || (linksElsewhere(e) && !!e.querySelector('img'));
      const pricesIn = (e, t) => {
        if (otherProduct(e)) return [];
        const withCur = [...t.matchAll(PRICE_RE)].map(m => ({ v: toNum(m[2] || m[3]), c: CUR_CODE[m[1] || m[4]] || (m[1] || m[4]) })).filter(x => x.v > 0);
        if (withCur.length) return withCur;
        if (e.closest(OTHER_PRODUCTS) || linksElsewhere(e)) return [];
        return barePrices(t).filter(v => v > 0).map(v => ({ v, c: pageCur }));
      };
      const cands = [...document.querySelectorAll('li,label,button,tr,div,a,option')].filter(e => {
        if (e.closest('[data-fn-host]')) return false;
        const raw = e.innerText || e.textContent || '';
        if (raw.length > 300 || !(e.offsetParent !== null || e.tagName === 'OPTION')) return false;
        const t = textOf(e);
        return SIZE_RE.test(t) && pricesIn(e, t).length > 0;
      });
      const minimal = cands.filter(e => !cands.some(o => o !== e && e.contains(o)));
      for (const e of minimal) {
        const t = textOf(e);
        const sizes = [...new Set([...t.matchAll(new RegExp(SIZE_RE.source, 'g'))].map(m => toNum(m[1])))];
        if (sizes.length !== 1) continue;                          // a whole size list: ambiguous
        const prices = pricesIn(e, t);
        if (!prices.length) continue;
        const best = prices.reduce((a, b) => (b.v < a.v ? b : a));  // lowest = the sale price
        add(map, sizes[0], best.v, best.c);
      }
    } catch {}
    // 3) Shops that show one price for the size you picked ("Size: 50 mL", a highlighted size button):
    //    pair the picked size with the price shown next to it.
    if (!map.size) {
      try {
        const LABEL_RE = /^(size|maat|inhoud|gr[öo](ss|ß)e|taille|formaat|contenance|volume|tama[ñn]o|taglia|formato|pojemno[śs][ćc])\s*:/i;
        const pickedClass = e => [...e.classList].some(c => /^(is-?)?(selected|active|checked|current)$|[-_](selected|active|checked|current)$/i.test(c));
        const picked = e => e.matches('[aria-checked="true"],[aria-selected="true"],[aria-pressed="true"],[aria-current="true"]') || pickedClass(e)
          || !!e.querySelector('input:checked') || (e.tagName === 'LABEL' && !!e.htmlFor && !!document.getElementById(e.htmlFor)?.checked);
        const short = e => withMl((e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim());
        const sizeEl = [...document.querySelectorAll('button,label,li,a,span,div,option')].find(e => {
          if (e.closest('[data-fn-host]') || e.closest(OTHER_PRODUCTS)) return false;
          const t = short(e);
          if (t.length > 40 || [...t.matchAll(new RegExp(SIZE_RE.source, 'g'))].length !== 1) return false;
          if (e.tagName === 'OPTION') return e.selected && e.parentElement?.offsetParent !== null;
          return e.offsetParent !== null && (picked(e) || LABEL_RE.test(t));
        });
        if (sizeEl) {
          const ml = toNum(short(sizeEl).match(SIZE_RE)[1]);
          for (let up = sizeEl.parentElement, i = 0; up && i < 6 && !map.size; up = up.parentElement, i++) {
            const priceEls = [...up.querySelectorAll('[class*="price" i]')].filter(e => e.offsetParent !== null && !e.closest(OTHER_PRODUCTS)
              && !/old|was|strike|before|regular|rrp|original/i.test(e.className) && getComputedStyle(e).textDecorationLine !== 'line-through');
            for (const e of priceEls) {
              const found = [...textOf(e).matchAll(PRICE_RE)].map(m => ({ v: toNum(m[2] || m[3]), c: CUR_CODE[m[1] || m[4]] || (m[1] || m[4]) })).filter(x => x.v > 0);
              if (found.length === 1) { add(map, ml, found[0].v, found[0].c); break; }
            }
          }
        }
      } catch {}
    }
    // 4) One price in the product data but no size in it (Mecca after picking a size): use the size in the
    //    page title, heading or address, if there is exactly one.
    if (!map.size) {
      try {
        const p = readProduct();
        const offers = [].concat(p?.offers || []).filter(o => o && /^\s*\d+(?:[.,]\d+)?\s*$/.test(String(o.price ?? '')));
        if (offers.length === 1) {
          for (const src of [document.title, document.querySelector('h1')?.innerText, decodeURIComponent(location.pathname).replace(/[-_/]+/g, ' ')]) {
            const sizes = [...new Set([...withMl(src).matchAll(new RegExp(SIZE_RE.source, 'g'))].map(m => toNum(m[1])))];
            if (sizes.length === 1) { add(map, sizes[0], parseFloat(offers[0].price), offers[0].priceCurrency); break; }
          }
        }
      } catch {}
    }
    // The shop's own product data wins over page text for the same size. Page-text prices for other sizes
    // must look like the same product, compared per ml with the nearest size from the product data:
    // a smaller bottle costs about the same or more per ml (0.85x-6x), a bigger one less (0.4x-1.3x).
    if (structured.size) {
      const refs = [...structured.values()];
      for (const [ml, v] of map) {
        if (structured.has(ml)) { map.delete(ml); continue; }
        const ref = refs.reduce((a, b) => (Math.abs(b.ml - ml) < Math.abs(a.ml - ml) ? b : a));
        const r = (v.price / v.ml) / (ref.price / ref.ml);
        if (ml < ref.ml ? r < 0.85 || r > 6 : r < 0.4 || r > 1.3) map.delete(ml);
      }
      for (const v of structured.values()) map.set(v.ml, v);
    }
    return [...map.values()].sort((a, b) => a.ml - b.ml).slice(0, 8);
  }

  // ---------- UI ----------
  const { CSS, flower, themeCss, renderBody, panelHtml, esc, localizeChrome } = FN_UI;

  const host = document.createElement('div');
  host.setAttribute('data-fn-host', '');
  host.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;display:flex;flex-direction:column;align-items:flex-end;gap:8px;';
  // The website's fonts for the panel. FontFace objects only download once text in the panel uses them,
  // through a per-session address (use_dynamic_url in the manifest). Own family names, so they can't clash
  // with the shop's fonts; if they can't load, the panel falls back to the system font.
  (() => {
    const LATIN = 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD';
    const LATIN_EXT = 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF';
    const families = [['FN Bricolage', 'bricolage-grotesque', [700, 800]], ['FN Figtree', 'figtree', [400, 600, 700]]];
    try {
      for (const [family, file, weights] of families) for (const w of weights) for (const [sub, range] of [['latin', LATIN], ['latin-ext', LATIN_EXT]]) {
        const url = chrome.runtime.getURL(`fonts/${file}-${sub}-${w}-normal.woff2`);
        document.fonts.add(new FontFace(family, `url("${url}") format("woff2")`, { weight: String(w), unicodeRange: range, display: 'swap' }));
      }
    } catch {}
  })();
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>${CSS}</style>
    <style class="theme"></style>
    <button class="pill" title="Show / hide fragrance notes" hidden>${flower(24)}</button>
    <div class="panel" hidden>${panelHtml}</div>`;
  document.documentElement.appendChild(host);

  const $ = s => root.querySelector(s);
  const pill = $('.pill'), panel = $('.panel'), body = $('.body'), input = $('input'), rz = $('.rz');

  let S = structuredClone(FN.DEFAULTS);
  let current = detect();
  let loadedFor = null;
  let lastRender = null;     // { data, cached, query } so settings changes can re-render
  let userClosed = false;    // don't auto-open again on this page after the user closed it

  // ---------- settings & look ----------
  const corner = () => S.position || 'br';
  // The resize zone sits on the panel's inner corner, diagonally away from the screen corner.
  const innerCorner = () => ({ br: 'tl', bl: 'tr', tr: 'bl', tl: 'br' })[corner()];

  function applySettings() {
    $('.theme').textContent = themeCss(FN.resolveTheme(S));
    const c = corner();
    host.style.top = c[0] === 't' ? '16px' : '';
    host.style.bottom = c[0] === 'b' ? '16px' : '';
    host.style.left = c[1] === 'l' ? '16px' : '';
    host.style.right = c[1] === 'r' ? '16px' : '';
    host.style.alignItems = c[1] === 'l' ? 'flex-start' : 'flex-end';
    rz.className = 'rz ' + innerCorner();
    panel.classList.toggle('simple', S.style === 'simple');
    localizeChrome(root, S.lang);
    if (!S.enabled) {
      panel.hidden = true;
      pill.hidden = true;
      return;
    }
    if (panel.hidden) pill.hidden = !current.show;
    if (lastRender) render(lastRender.data, lastRender.cached, lastRender.query);
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'sync' && changes.settings) {
      FN.loadSettings().then(s => {
        const wasEnabled = S.enabled, oldLang = S.lang;
        S = s;
        applySettings();
        if (S.enabled && !wasEnabled) prefetch();
        // New language: look the current perfume up again on that language's site.
        else if (S.lang !== oldLang && loadedFor) lookup(loadedFor);
      });
    }
    if (area === 'local' && changes['fn:size'] && !changes['fn:size'].newValue) resetSize();
  });

  // Search field: hidden behind the magnifier, shown when nothing was found or there's nothing to look up.
  const showSearch = (on = true, focus = false) => {
    panel.classList.toggle('searching', on);
    if (on && focus) setTimeout(() => { input.focus(); input.select(); }, 0);
  };
  $('.srch').addEventListener('click', e => {
    e.stopPropagation();
    showSearch(!panel.classList.contains('searching'), true);
  });

  $('.gear').addEventListener('click', e => {
    e.stopPropagation();
    chrome.runtime.sendMessage({ type: 'open-options' }).catch(() => {});
  });

  $('.x').addEventListener('click', e => { e.stopPropagation(); close(); });
  $('.hfav').addEventListener('click', e => { e.stopPropagation(); chrome.runtime.sendMessage({ type: 'open-favs' }).catch(() => {}); });

  // ---------- resizing (drag the inner corner) ----------
  function setSize(w, h) {
    const maxW = window.innerWidth - 32, maxH = window.innerHeight - 100;
    panel.style.width = Math.max(280, Math.min(w, maxW)) + 'px';
    panel.style.height = Math.max(220, Math.min(h, maxH)) + 'px';
    panel.classList.add('sized');
  }
  function resetSize() {
    panel.style.width = '';
    panel.style.height = '';
    panel.classList.remove('sized');
  }
  chrome.storage.local.get('fn:size').then(r => { const s = r['fn:size']; if (s) setSize(s.w, s.h); }).catch(() => {});

  rz.addEventListener('pointerdown', e => {
    e.preventDefault();
    rz.setPointerCapture(e.pointerId);
    const r = panel.getBoundingClientRect();
    const start = { x: e.clientX, y: e.clientY, w: r.width, h: r.height };
    const ic = innerCorner();
    const sx = ic[1] === 'l' ? -1 : 1;   // dragging left grows a left-side corner
    const sy = ic[0] === 't' ? -1 : 1;   // dragging up grows a top-side corner
    const move = ev => setSize(start.w + sx * (ev.clientX - start.x), start.h + sy * (ev.clientY - start.y));
    const up = () => {
      rz.removeEventListener('pointermove', move);
      rz.removeEventListener('pointerup', up);
      const b = panel.getBoundingClientRect();
      chrome.storage.local.set({ 'fn:size': { w: Math.round(b.width), h: Math.round(b.height) } }).catch(() => {});
    };
    rz.addEventListener('pointermove', move);
    rz.addEventListener('pointerup', up);
  });
  rz.addEventListener('dblclick', () => { resetSize(); chrome.storage.local.remove('fn:size').catch(() => {}); });

  // ---------- open / close ----------
  function open(auto = true) {
    if (!S.enabled) return;
    pill.hidden = false;
    panel.hidden = false;
    pill.classList.remove('ready');
    if (!input.value && current.isProduct) input.value = current.query;
    if (auto && input.value && loadedFor !== input.value) lookup(input.value);
    else if (!input.value) { body.innerHTML = `<div class="msg muted">${esc(FN.t(S.lang, 'typeHint'))}</div>`; showSearch(true, true); }
    if (pendingWork) { const go = pendingWork; pendingWork = null; go(); }
  }
  function close() {
    panel.hidden = true;
    pill.hidden = !current.show;
    userClosed = true;
  }

  pill.addEventListener('click', () => (panel.hidden ? open() : close()));
  $('form').addEventListener('submit', e => {
    e.preventDefault();
    const q = input.value.trim();
    if (q) lookup(q, true);
  });

  // ---------- lookup ----------
  // Search in the background as soon as a product page loads, so results are ready.
  // Follow the system's light/dark switch while the page is open.
  try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (S.themeAuto) { applySettings(); if (lastRender) render(lastRender.data, lastRender.cached, lastRender.query); } }); } catch {}

  // Grey placeholder in the shape of the results, so the panel doesn't jump when the data arrives.
  const skeleton = () => `<div class="skel" aria-busy="true" aria-label="${esc(FN.t(S.lang, 'looking'))}">
      <div class="sk-hero"><i class="sk sk-photo"></i><div><i class="sk sk-l w70"></i><i class="sk sk-l w40"></i></div></div>
      <div class="sk-tiles"><i class="sk"></i><i class="sk"></i><i class="sk"></i><i class="sk"></i></div>
      <i class="sk sk-h"></i>${[100, 72, 66, 58, 50].map(w => `<i class="sk sk-bar" style="width:${w}%"></i>`).join('')}
      <i class="sk sk-h"></i><div class="sk-chips">${[70, 90, 60, 80, 75, 65].map(w => `<i class="sk" style="width:${w}px"></i>`).join('')}</div>
    </div>`;
  // A dot on the flower button once the results are ready (cleared when the panel is opened).
  const setReady = on => pill.classList.toggle('ready', !!on && panel.hidden);

  function prefetch() {
    if (!S.enabled || !current.show) return;
    shareFactsLater();
    if (!(S.autoSearch || S.autoOpen)) return;
    input.value = current.query;
    if (current.query && loadedFor !== current.query) lookup(current.query);
  }

  async function lookup(query, force = false, alias = '') {
    loadedFor = query;
    lastRender = null;
    pill.classList.add('loading');
    setReady(false);
    body.innerHTML = skeleton();
    let res;
    try {
      res = await chrome.runtime.sendMessage({ type: 'lookup', query, force, lang: S.lang, alias });
    } catch {
      pill.classList.remove('loading');
      body.innerHTML = `<div class="msg">${esc(FN.t(S.lang, 'reloaded'))}</div>`;
      return;
    }
    if (loadedFor !== query) return; // a newer search started
    pill.classList.remove('loading');
    if (res.error) {
      renderError(res, query);
      // Fragrantica has nothing (or can't be reached): the database's confirmed notes, if it has them.
      if (current.isProduct && query === current.query) {
        askOwn(current.isProduct && !current.isSet ? readPrices() : []).then(p => {
          const notes = ownPyramid(p);
          if (!notes || loadedFor !== query || lastRender) return;
          const d = { title: `${p.brand} ${p.name}`.trim(), url: '', notes, accords: [] };
          ownByPage.set(d, p);
          render(d, false, query);
          setReady(true);
        });
      }
      return;
    }
    render(res.data, !!res.cached, query);
    setReady(true);
    if (S.autoOpen && panel.hidden && !userClosed && current.show) open(false);
  }

  // ---------- rendering ----------
  // After searching for something else, offer a way back to the perfume on this page.
  function addBackLink(query) {
    if (!current.show || !current.query || query === current.query) return;
    const b = document.createElement('button');
    b.className = 'linkbtn back';
    b.textContent = '↩ ' + current.query;
    b.addEventListener('click', () => { input.value = current.query; lookup(current.query); });
    body.appendChild(b);
  }

  function renderError(res, query) {
    showSearch(true);
    let html;
    if (res.error === 'notfound' && res.candidates?.length) {
      // Show the closest Fragrantica perfumes so the user can pick the right one.
      body.innerHTML = `<div class="msg">${esc(FN.t(S.lang, 'didYouMean'))}<div class="cands">${res.candidates.map((c, i) =>
        `<button class="cand" data-i="${i}">${/^data:image\//.test(c.img) ? `<img src="${esc(c.img)}" alt="">` : ''}<span><span class="n">${esc(c.name)}</span><span class="b">${esc(c.brand)}</span></span></button>`).join('')}</div></div>`;
      addBackLink(query);
      body.querySelectorAll('.cand').forEach(b => b.addEventListener('click', () => {
        const c = res.candidates[+b.dataset.i];
        input.value = c.url;
        lookup(c.url, false, query);
      }));
      return;
    } else if (res.error === 'notfound') {
      html = esc(FN.t(S.lang, 'notFound'));
    } else {
      // Blocked / unreadable / anything else: a short message in the chosen language, plus a link to the page.
      const key = res.error === 'blocked' || res.error === 'timeout' ? 'blocked' : res.error === 'empty' ? 'unreadable' : 'failed';
      const link = res.url || (key === 'blocked' ? 'https://www.fragrantica.com/' : '');
      html = esc(FN.t(S.lang, key)) + (link ? `<br><a href="${esc(link)}" target="_blank">${esc(FN.t(S.lang, 'openFrag'))} ↗</a>` : '');
    }
    body.innerHTML = `<div class="msg">${html}</div>`;
    addBackLink(query);
  }

  // ---------- prices at other shops ----------
  // Every shop page where we read sizes and prices is remembered locally (per Fragrantica perfume),
  // so other shops can show "price per ml at other shops". Nothing leaves the browser.
  const SEEN_KEY = 'fn:seen';
  // ---------- messages from the toolbar menu ----------
  chrome.runtime.onMessage.addListener((msg, sender, send) => {
    if (msg?.type === 'fn:status') {
      send({ product: !!current.show, name: lastRender?.data?.title || (current.show ? current.query : ''), ready: !!lastRender, open: !panel.hidden });
    } else if (msg?.type === 'fn:open') {
      // Back to the perfume on this page, even after searching for something else.
      userClosed = false;
      if (current.show && current.query && input.value !== current.query) input.value = current.query;
      open();
      send({ ok: true });
    } else if (msg?.type === 'fn:search' && msg.query) {
      userClosed = false;
      open(false);
      input.value = msg.query;
      lookup(msg.query);
      send({ ok: true });
    }
  });

  // ---------- note details (click a note) ----------
  // Shows the note's scent description from its Fragrantica page right under that row of notes.
  const noteCache = new Map();
  function showNote(chip) {
    const tier = chip.closest('.tier') || chip.parentElement;
    const open = body.querySelector('.notepop');
    const same = chip.classList.contains('on');
    body.querySelectorAll('.chip.nb.on').forEach(c => c.classList.remove('on'));
    open?.remove();
    if (same) return;
    chip.classList.add('on');
    const { note: url, name, img } = chip.dataset;
    const pop = document.createElement('div');
    pop.className = 'notepop';
    const fill = info => {
      const link = `<a href="${FN_UI.esc(url)}" target="_blank">Fragrantica ↗</a>`;
      const E = FN_UI.esc;
      pop.innerHTML = `${img ? `<img src="${E(img)}" alt="">` : '<span></span>'}<div><div class="nn"><span>${E(name)}${
        info?.latin ? ` <i class="lat">${E(info.latin)}</i>` : ''}</span>${link}</div>${
        !info ? '<span class="spin sm"></span>'
        : (info.facts || []).map(f => `<div class="nl">${E(f.label)}</div><div>${E(f.text)}</div>`).join('')}</div>`;
    };
    fill(noteCache.get(url));
    tier.appendChild(pop);
    if (!noteCache.has(url)) {
      chrome.runtime.sendMessage({ type: 'note', url }).then(info => {
        noteCache.set(url, info || {});
        if (pop.isConnected) fill(noteCache.get(url));
      }).catch(() => { if (pop.isConnected) fill({}); });
    }
  }
  body.addEventListener('click', e => {
    const chip = e.target.closest('.chip.nb');
    if (chip) showNote(chip);
  });
  body.addEventListener('keydown', e => {
    const chip = e.target.closest('.chip.nb');
    if (chip && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); showNote(chip); }
  });

  let pendingWork = null;
  // Perfumes the user actually looked at (panel open with a result), once per perfume per page. Only a number,
  // kept in this browser: the toolbar menu asks for a store review once it reaches 10.
  const counted = new Set();
  const countLookup = d => {
    if (!d?.url || counted.has(d.url)) return;
    counted.add(d.url);
    chrome.storage.local.get('fn:lookups').then(o => chrome.storage.local.set({ 'fn:lookups': (o['fn:lookups'] || 0) + 1 })).catch(() => {});
  };
  let pricesOpen = false;
  const factsSent = new Set();   // product pages whose facts were sent (once per page load)
  // The facts normally go once the panel has found the perfume on Fragrantica (so they carry its number). When that
  // takes long, fails, or waits for a click (automatic search off), they go anyway after a few seconds on the page:
  // what a shop or brand site says is worth keeping without Fragrantica.
  let factsTimer = 0;
  function shareFactsLater() {
    const path = location.pathname;
    clearTimeout(factsTimer);
    factsTimer = setTimeout(() => {
      if (location.pathname !== path || factsSent.has(path) || !S.shareFacts || !current.isProduct || current.isSet
        || !FN.builtInShop(location.hostname)) return;
      factsSent.add(path);
      try { chrome.runtime.sendMessage({ type: 'facts', perfumeId: '', facts: readFacts(current, readPrices()) }).catch(() => {}); } catch {}
    }, 5000);
  }
  const perfumeId = url => (String(url || '').match(/-(\d+)\.html/) || [])[1];

  // ---------- own database first ----------
  // What the Fragrance Notes database knows about the perfume on this page (background.js → GET /catalog/lookup).
  const ownByPage = new WeakMap();   // Fragrantica result → database perfume
  const askOwn = prices => {
    try { return chrome.runtime.sendMessage({ type: 'own', facts: readFacts(current, prices) }).catch(() => null); }
    catch { return Promise.resolve(null); }
  };
  const plainName = s => String(s || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const titleCase = s => String(s).replace(/(^|\s)\p{L}/gu, m => m.toUpperCase());
  // A note as one key across languages and spellings: its English name from NOTE_GROUPS ("Viooltjesblad",
  // "vioolblaadjes" → "violet leaf"), else its plain name with a plural ending dropped ("kastanjes" = "kastanje").
  const noteKeyOf = s => {
    const p = plainName(s);
    const stem = p.length > 4 ? p.replace(/(?:en|es|s)$/, '') : p;
    return NOTE_GROUPS.get(p) || NOTE_GROUPS.get(stem) || stem;
  };
  // While the database grows, the panel keeps Fragrantica's notes and marks the ones the database confirmed
  // (2+ shops agree) with ✓. Returns null when none of this perfume's Fragrantica notes is confirmed, so the
  // panel then looks exactly as before.
  function ownChecks(d) {
    const p = ownByPage.get(d);
    const keys = new Set();
    for (const tier of ['top', 'heart', 'base']) {
      for (const n of p?.notes?.[tier] || []) {
        if (n.confirmed) [n.key, n.en, n.name].filter(Boolean).forEach(x => keys.add(noteKeyOf(x)));
      }
    }
    if (!keys.size) return null;
    const has = name => keys.has(noteKeyOf(name));
    return (d.notes || []).some(t => (t.names || []).some(n => has(n.name))) ? { has, shops: p.shops } : null;
  }
  // "Own it? Rate it": the perfume's rating page on fragrancenotes.app (voting is on the website, no account),
  // in the panel's language when the site has it. Only when the database knows this perfume.
  const SITE_LANGS = ['nl', 'de', 'fr', 'es', 'it', 'pt', 'pl'];
  function rateUrl(d) {
    const id = ownByPage.get(d)?.id;
    if (!/^[0-9a-f]{12}$/.test(id || '')) return null;
    return `https://fragrancenotes.app${SITE_LANGS.includes(S.lang) ? '/' + S.lang : ''}/perfume/${id}/rate`;
  }
  // Only when Fragrantica has nothing for this page: the database's confirmed notes as the pyramid (no pictures),
  // if there are at least FN.OWN_MIN_CONFIRMED of them.
  function ownPyramid(p) {
    if (!p || (p.confirmedNotes || 0) < FN.OWN_MIN_CONFIRMED) return null;
    const tiers = [['top', 'tierTop'], ['heart', 'tierHeart'], ['base', 'tierBase']].map(([tier, label]) => ({
      label: FN.t(S.lang, label),
      names: (p.notes?.[tier] || []).filter(n => n.confirmed)
        .map(n => ({ name: S.lang === 'en' && n.en ? titleCase(n.en) : n.name, img: '', url: '' }))
    })).filter(t => t.names.length);
    return tiers.length ? tiers : null;
  }
  async function seenPrices(d, prices) {
    const id = perfumeId(d.url);
    if (!id) return [];
    const host = location.hostname.replace(/^www\./, '');
    let all = {};
    try { all = (await chrome.storage.local.get(SEEN_KEY))[SEEN_KEY] || {}; } catch { return []; }
    const cutoff = Date.now() - 90 * 864e5;
    let list = (all[id] || []).filter(o => o.t > cutoff && o.host !== host);
    if (prices.length && current.isProduct) {
      const best = prices.reduce((a, b) => (b.price / b.ml < a.price / a.ml ? b : a));
      const mine = { host, url: location.href.split('#')[0], per: best.price / best.ml, ml: best.ml, currency: best.currency || 'EUR', t: Date.now() };
      all[id] = [mine, ...list].slice(0, 20);
      // Keep the store small: at most 300 perfumes, newest first.
      const ids = Object.keys(all).sort((a, b) => Math.max(...all[b].map(o => o.t)) - Math.max(...all[a].map(o => o.t)));
      ids.slice(300).forEach(k => delete all[k]);
      try { await chrome.storage.local.set({ [SEEN_KEY]: all }); } catch {}
    }
    return list.sort((a, b) => a.per - b.per).slice(0, 6);
  }

  async function render(d, cached, query) {
    if (lastRender?.data !== d) showSearch(false);
    lastRender = { data: d, cached, query };
    pendingWork = null;
    const prices = current.isProduct && !current.isSet ? readPrices() : [];   // a set price is not the bottle price
    const elsewhere = S.sections.elsewhere ? await seenPrices(d, prices) : [];
    if (lastRender?.data !== d) return;    // a newer render started meanwhile
    const builtIn = !!FN.builtInShop(location.hostname);
    const opts = { cached, query, prices: S.sections.perMl ? prices : [], elsewhere, othersAll: false, host: location.hostname, pricesOpen, community: null,
      askShare: !S.sharePrices && !S.shareFacts && !S.shareAsked && builtIn, teaser: !S.sharePrices && builtIn,
      own: ownChecks(d), rate: rateUrl(d) };
    opts.fav = perfumeId(d.url) ? { on: await FN.favs.has(perfumeId(d.url)) } : null;
    if (lastRender?.data !== d) return;
    const paint = () => {
      body.innerHTML = renderBody(d, S, opts);
      body.querySelector('.refresh')?.addEventListener('click', () => lookup(query, true));
      body.querySelector('.more')?.addEventListener('click', () => { opts.othersAll = true; paint(); });
      // The one-time "help other perfume lovers?" card: yes turns on both sharing settings (prices and the
      // open perfume database; Settings → Data has one switch for both too). Saving the settings redraws the panel
      // (see applySettings), which then fetches and shares when sharing was turned on.
      const answer = on => {
        if (on) { S.sharePrices = true; S.shareFacts = true; }
        else chrome.storage.local.set({ 'fn:shareDeclined': true }).catch(() => {});   // the toolbar menu won't ask either
        S.shareAsked = true;
        chrome.storage.sync.set({ settings: S }).catch(() => {});
      };
      body.querySelector('.ask-on')?.addEventListener('click', () => answer(true));
      body.querySelector('.ask-no')?.addEventListener('click', () => answer(false));
      // "Compare prices with other users →" (sharing off): shows the card again, with its explanation.
      body.querySelector('.teaser')?.addEventListener('click', () => { opts.askShare = true; paint(); });
      // ♥ saves the perfume to the favourites (toolbar menu → Favourites).
      body.querySelector('.fav')?.addEventListener('click', async e => {
        const btn = e.currentTarget;
        const on = !opts.fav.on;
        const ok = on ? await FN.favs.add(d) : (await FN.favs.remove(perfumeId(d.url)), true);
        if (!ok) return;
        opts.fav.on = on;
        btn.classList.toggle('on', on);
        btn.classList.toggle('pop', on);
        btn.setAttribute('aria-pressed', String(on));
        btn.title = FN.t(S.lang, on ? 'faved' : 'fav');
      });
      body.querySelector('details.others')?.addEventListener('toggle', e => {
        if (e.target.open === pricesOpen) return;
        pricesOpen = opts.pricesOpen = e.target.open;
      });
      body.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
        img.parentElement?.classList.add('noimg');
        img.remove();
      }));
    };
    // Pros & cons exist only on the English Fragrantica site: fetch them once for other languages.
    // (It opens a background tab, so only once the panel is actually open.)
    const askOpinions = () => {
      if (S.sections.prosCons === false || d.prosCons || !d.url || /\/\/www\.fragrantica\.com\//.test(d.url) || d._pcAsked) return;
      d._pcAsked = true;
      chrome.runtime.sendMessage({ type: 'opinions', url: d.url }).then(pc => {
        if (pc && (pc.pros?.length || pc.cons?.length)) {
          d.prosCons = pc;
          if (lastRender?.data === d) paint();
        }
      }).catch(() => {});
    };
    if (!panel.hidden) { askOpinions(); countLookup(d); }
    else { const prev = pendingWork; pendingWork = () => { prev?.(); askOpinions(); countLookup(d); }; }
    pricesOpen = opts.pricesOpen = false;   // the other-shops list always starts closed
    paint();
    priceWatch = { d, opts, paint, pid: perfumeId(d.url) };

    // Ask the Fragrance Notes database about this shop's perfume (anonymous, for everyone) and mark the notes it
    // confirmed with ✓. Nothing changes when it doesn't know the perfume or can't be reached.
    if (!opts.own && current.isProduct && query === current.query) {
      askOwn(prices).then(p => {
        if (!p || lastRender?.data !== d) return;
        ownByPage.set(d, p);
        opts.own = ownChecks(d);
        opts.rate = rateUrl(d);
        if (opts.own || opts.rate) paint();
      });
    }

    // "Help build the open perfume database" (off by default): the facts this shop shows about the perfume.
    if (S.shareFacts && current.isProduct && !current.isSet && FN.builtInShop(location.hostname) && !factsSent.has(location.pathname)) {
      factsSent.add(location.pathname);
      try { chrome.runtime.sendMessage({ type: 'facts', perfumeId: perfumeId(d.url) || '', facts: readFacts(current, prices) }).catch(() => {}); } catch {}
    }

    // "Share prices anonymously" (off by default): first get other users' prices for this perfume,
    // then share the ones on this page, so your own report doesn't count in the label you see.
    const pid = perfumeId(d.url);
    if (!S.sharePrices || !pid) return;
    const currency = prices.find(p => p.currency)?.currency;
    const community = await chrome.runtime.sendMessage({ type: 'community', perfumeId: pid, currency }).catch(() => null);
    if (prices.length && current.isProduct) chrome.runtime.sendMessage({ type: 'share', perfumeId: pid, prices }).catch(() => {});
    if (community?.count && lastRender?.data === d) { opts.community = community; paint(); }
  }

  // Some shops only show every size after a click ("show all 5 sizes", a size dropdown). After a click on
  // the page, read the prices again and add sizes or prices that weren't there yet.
  let priceWatch = null, priceTimer = 0;
  const recheckPrices = e => {
    if (!priceWatch || e.target?.closest?.('[data-fn-host]')) return;
    clearTimeout(priceTimer);
    priceTimer = setTimeout(() => {
      const w = priceWatch;
      if (!w || lastRender?.data !== w.d || !current.isProduct || current.isSet || !S.sections.perMl) return;
      const byMl = new Map(w.opts.prices.map(p => [p.ml, p]));
      const added = readPrices().filter(p => byMl.get(p.ml)?.price !== p.price);
      if (!added.length) return;
      added.forEach(p => byMl.set(p.ml, p));
      w.opts.prices = [...byMl.values()].sort((a, b) => a.ml - b.ml).slice(0, 8);
      w.paint();
      if (S.sharePrices && w.pid) chrome.runtime.sendMessage({ type: 'share', perfumeId: w.pid, prices: added }).catch(() => {});
    }, 900);
  };
  document.addEventListener('click', recheckPrices, true);
  document.addEventListener('change', recheckPrices, true);

  // ---------- keyboard shortcut (set in Settings; empty = off) ----------
  const comboOf = e => {
    const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(k)) return '';
    return [e.ctrlKey && 'Ctrl', e.altKey && 'Alt', e.shiftKey && 'Shift', e.metaKey && 'Meta', e.code?.startsWith('Key') ? e.code.slice(3) : e.code?.startsWith('Digit') ? e.code.slice(5) : k]
      .filter(Boolean).join('+');
  };
  // Esc closes the open panel (unless someone is typing in a field on the page itself).
  window.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || panel.hidden) return;
    const inPanel = e.composedPath().includes(host);
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName) || e.target?.isContentEditable;
    if (typing && !inPanel) return;
    close();
  }, true);
  window.addEventListener('keydown', e => {
    if (!S.enabled || !S.shortcut) return;
    if (comboOf(e) !== S.shortcut) return;
    // Plain keys shouldn't fire while typing in a field.
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName) || e.target?.isContentEditable;
    if (typing && !(e.ctrlKey || e.altKey || e.metaKey)) return;
    e.preventDefault();
    e.stopPropagation();
    if (panel.hidden) open(current.isProduct); else close();
  }, true);

  // ---------- wiring ----------
  FN.loadSettings().then(s => {
    S = s;
    applySettings();
    prefetch();
    if (!current.show) waitForProduct();
  });

  // Some shops render the product name or data a few seconds after the page loads: keep looking for a while.
  let waitTimer = null;
  function waitForProduct(delays = [700, 1500, 2500, 4000, 6000, 9000]) {
    clearTimeout(waitTimer);
    const url = location.href;
    const step = i => {
      if (i >= delays.length || location.href !== url) return;
      waitTimer = setTimeout(() => {
        if (location.href !== url) return;
        const d = detect();
        if (!d.show) return step(i + 1);
        current = d;
        if (S.enabled && panel.hidden) { pill.hidden = false; prefetch(); }
      }, delays[i] - (delays[i - 1] || 0));
    };
    step(0);
  }

  // Many shops are single-page apps: re-detect when the URL changes.
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    const prevQuery = current.query;
    let tries = 0;
    const recheck = () => {
      current = detect();
      // Give slow pages a few more seconds to swap in the new product.
      if (current.show && current.query === prevQuery && ++tries < 4) return setTimeout(recheck, 800);
      input.value = '';
      pendingWork = null;
      loadedFor = null;
      lastRender = null;
      userClosed = false;
      pill.classList.remove('loading', 'ready');
      body.innerHTML = '';
      if (!S.enabled || !current.show) { panel.hidden = true; pill.hidden = true; if (!current.show) waitForProduct(); }
      else if (panel.hidden) { pill.hidden = false; prefetch(); }
      else open();
    };
    setTimeout(recheck, 1000);
  }, 800);
})();
