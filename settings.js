// Shared by the content script, the options page and the toolbar popup.
(() => {
  const DEFAULTS = {
    enabled: true,         // master switch (toolbar popup)
    autoSearch: true,      // look up the perfume as soon as a product page loads
    allSites: false,       // also run on every website (needs the optional all-sites permission)
    autoOpen: false,       // open the panel by itself when results are found
    position: 'br',        // corner: 'br' | 'bl' | 'tr' | 'tl'
    theme: 'plum',
    style: 'rich',         // 'rich' (photos + accord colours) | 'simple'
    accStyle: 'strip',     // accords as one colour 'strip' or 'bars'
    themeAuto: false,      // follow the system's light/dark mode (uses the light or dark version of the chosen colour)
    lang: 'en',            // Fragrantica language site to read from
    shortcut: '',          // keyboard shortcut to show/hide the panel, e.g. "Alt+F" (empty = none)
    sharePrices: false,    // opt-in: share prices seen on built-in shops anonymously, and show other users' prices
    shareFacts: false,     // opt-in: send the facts a built-in shop shows about a perfume to the open perfume database
    shareAsked: false,     // the one-time card in the panel asking to turn sharing on was answered
    sections: {
      summary: true, photo: true, meta: true, perMl: true, elsewhere: true, accords: true, notes: true, wear: true, prosCons: true,
      longevity: true, sillage: true, priceValue: true, gender: true, dupes: true, similar: true
    }
  };

  // "What to show" in settings, in the same order as the panel (top to bottom). [key, title, description]
  const SECTION_GROUPS = [
    { key: 'header', items: [
      ['photo', 'Perfume photo', ''], ['meta', 'Year, gender & rating', ''], ['summary', 'Summary', '']
    ] },
    { key: 'scent', items: [['accords', 'Main accords', ''], ['notes', 'Notes', '']] },
    { key: 'wear', items: [['wear', 'When to wear', ''], ['prosCons', 'Pros & cons', '']] },
    { key: 'votes', items: [['longevity', 'Longevity', ''], ['sillage', 'Sillage', ''], ['priceValue', 'Price value', ''], ['gender', 'Gender', '']] },
    { key: 'prices', items: [['perMl', 'Price per ml', ''], ['elsewhere', 'Other shops', '']] },
    { key: 'similar', items: [['similar', 'Reminds people of', ''], ['dupes', 'Cheaper alternatives (dupes)', '']] }
  ];
  const SECTION_LABELS = Object.fromEntries(SECTION_GROUPS.flatMap(g => g.items.map(([k, t]) => [k, t])));


  // Each theme sets the panel's CSS variables. Every colour has a light and a dark version.
  const THEMES = {
    plum: {
      name: 'Plum', bg: '#fffdfb', fg: '#2b1426', muted: '#5e4a59', label: '#8a6b80',
      head: '#2b1d2e', headFg: '#f6e9f2', accent: '#7e2f63', soft: '#c58bb0',
      chip: '#f4eef3', card: '#f8f1f6', border: '#e3d6e0', input: '#ffffff', inputBorder: '#dccdd8'
    },
    iris: {
      name: 'Iris', bg: '#fcfcfe', fg: '#1f1d29', muted: '#7d7a8c', label: '#6c6890',
      head: '#25223b', headFg: '#ecebf7', accent: '#5d58a6', soft: '#b5b1e0',
      chip: '#efeef8', card: '#f6f5fb', border: '#e6e4f2', input: '#ffffff', inputBorder: '#d1cee6'
    },
    amber: {
      name: 'Amber', bg: '#fffcf7', fg: '#2a2118', muted: '#8c7d6c', label: '#9a7448',
      head: '#2e2217', headFg: '#f6ead9', accent: '#a8692a', soft: '#e0bb8e',
      chip: '#f6ecdf', card: '#fbf5ec', border: '#efe3d3', input: '#ffffff', inputBorder: '#e0cfb9'
    },
    minimal: {
      name: 'Minimal', bg: '#ffffff', fg: '#1f2328', muted: '#6b7280', label: '#6b7280',
      head: '#f3f4f6', headFg: '#1f2328', accent: '#374151', soft: '#c3c7cf',
      chip: '#f3f4f6', card: '#f7f7f8', border: '#e5e7eb', input: '#ffffff', inputBorder: '#d1d5db'
    },
    plumDark: {
      name: 'Plum', dark: true, bg: '#1d1a1f', fg: '#efe8ee', muted: '#a59aa3', label: '#c49ab5',
      head: '#121014', headFg: '#f3e9f0', accent: '#e48ab8', soft: '#8f5a78',
      chip: '#2c2730', card: '#262229', border: '#332d36', input: '#151316', inputBorder: '#4a414d', onAccent: '#121014'
    },
    irisDark: {
      name: 'Iris', dark: true, bg: '#18171f', fg: '#e9e8f2', muted: '#a09eb2', label: '#aaa6dd',
      head: '#0f0e15', headFg: '#e9e8f5', accent: '#a7a3f2', soft: '#4d4a7a',
      chip: '#25243a', card: '#201f2a', border: '#2c2a3a', input: '#121118', inputBorder: '#403e57', onAccent: '#121118'
    },
    amberDark: {
      name: 'Amber', dark: true, bg: '#1c1814', fg: '#f1e8dc', muted: '#a89a89', label: '#d9a56b',
      head: '#120f0c', headFg: '#f3e6d4', accent: '#e3a45f', soft: '#7a5530',
      chip: '#2b241d', card: '#241e18', border: '#342b22', input: '#14110e', inputBorder: '#4a3e31', onAccent: '#1c1206'
    },
    minimalDark: {
      name: 'Minimal', dark: true, bg: '#18181b', fg: '#e4e4e7', muted: '#a1a1aa', label: '#a1a1aa',
      head: '#27272a', headFg: '#e4e4e7', accent: '#d4d4d8', soft: '#52525b',
      chip: '#27272a', card: '#202023', border: '#2e2e33', input: '#111113', inputBorder: '#3f3f46', onAccent: '#18181b'
    }
  };

  // Fragrantica's language sites (from the hreflang links on its pages): host + perfume path.
  const LANGS = {
    en: { name: 'English', host: 'www.fragrantica.com', path: 'perfume' },
    nl: { name: 'Nederlands', host: 'www.fragrantica.nl', path: 'parfum' },
    de: { name: 'Deutsch', host: 'www.fragrantica.de', path: 'Parfum' },
    fr: { name: 'Français', host: 'www.fragrantica.fr', path: 'parfum' },
    es: { name: 'Español', host: 'www.fragrantica.es', path: 'perfume' },
    it: { name: 'Italiano', host: 'www.fragrantica.it', path: 'perfume' },
    pt: { name: 'Português (Brasil)', host: 'www.fragrantica.com.br', path: 'perfume' },
    pl: { name: 'Polski', host: 'www.fragrantica.pl', path: 'perfumy' },
    cs: { name: 'Čeština', host: 'www.fragrantica.cz', path: 'perfume' },
    ro: { name: 'Română', host: 'www.fragrantica.ro', path: 'parfum' },
    hu: { name: 'Magyar', host: 'www.fragrantica.hu', path: 'perfumes' },
    sv: { name: 'Svenska', host: 'www.fragrantica.se', path: 'perfumes' },
    el: { name: 'Ελληνικά', host: 'www.fragrantica.gr', path: 'perfume' },
    tr: { name: 'Türkçe', host: 'www.fragrantica.tr', path: 'perfumes' },
    ru: { name: 'Русский', host: 'www.fragrantica.ru', path: 'perfume' },
    uk: { name: 'Українська', host: 'www.fragrantica.ua', path: 'perfumes' },
    sr: { name: 'Srpski', host: 'www.punmiris.com', path: 'parfem' },
    mn: { name: 'Монгол', host: 'www.fragrantica.mn', path: 'perfumes' },
    ar: { name: 'العربية', host: 'www.fragranticarabia.com', path: 'perfumes' },
    he: { name: 'עברית', host: 'www.fragrantica.co.il', path: 'perfumes' },
    zh: { name: '中文', host: 'www.fragrantica.asia', path: 'perfume' },
    ja: { name: '日本語', host: 'www.fragrantica.jp', path: 'perfume' },
    ko: { name: '한국어', host: 'www.fragrantica.kr', path: 'perfumes' }
  };
  const LANG_HOSTS = Object.values(LANGS).map(l => l.host);

  // Panel text the extension adds itself lives in i18n-panel.js (all 23 languages).
  // Section titles and vote labels normally come from Fragrantica; these are fallbacks.
  // Which browser and store this copy came from. The review link points to the store it was installed
  // from; null (no review request) for an unknown ID, such as an unpacked copy.
  const IS_FIREFOX = typeof chrome !== 'undefined' && !!chrome.runtime?.getURL && chrome.runtime.getURL('').startsWith('moz-extension:');
  const REVIEW_URL = ({
    hhhiolpcmkdkegcmjmpglcnfolohldgc: 'https://chromewebstore.google.com/detail/fragrance-notes/hhhiolpcmkdkegcmjmpglcnfolohldgc/reviews',
    'fragrance-notes@fragrancenotes.app': 'https://addons.mozilla.org/firefox/addon/fragrance-notes/reviews/',
    // Edge Add-ons: add the ID and link here once the listing is live.
  })[typeof chrome !== 'undefined' && chrome.runtime?.id] || null;

  const PANEL_KEYS = ['title', 'search', 'placeholder', 'notes', 'priceValue', 'data', 'cached', 'refresh', 'looking', 'noNotes', 'dupes', 'dupe', 'perMl', 'elsewhere', 'didYouMean', 'notFound', 'pros', 'cons', 'prosCons', 'rating', 'typeHint', 'reloaded', 'blocked', 'unreadable', 'failed', 'openFrag', 'notAffiliated', 'great', 'fair', 'over', 'community', 'dealTip', 'lowestKnown', 'cheapestAt', 'typicalAt', 'shareAsk', 'shareAskD', 'shareOn', 'shareNo', 'privacy', 'lowest30', 'cheapestShort', 'typicalShort', 'close', 'fav', 'faved', 'favs', 'tierTop', 'tierHeart', 'tierBase', 'ownNotes', 'shareTeaser', 'rateIt', 'smellsLike', 'comesFrom', 'moreOnSite'];
  const EN_FALLBACK = { accords: 'Main accords', wear: 'When to wear', longevity: 'Longevity', sillage: 'Sillage', gender: 'Gender', similar: 'Reminds people of' };
  const t = (lang, key) => {
    const table = globalThis.FN_PANEL_I18N || {};
    const i = PANEL_KEYS.indexOf(key);
    if (i >= 0) return (table[lang] && table[lang][i]) || (table.en && table.en[i]) || key;
    return EN_FALLBACK[key] || key;
  };

  async function load() {
    try {
      const { settings } = await chrome.storage.sync.get('settings');
      const s = settings || {};
      const out = { ...DEFAULTS, ...s, sections: { ...DEFAULTS.sections, ...(s.sections || {}) } };
      // Migrate values from older versions.
      if (out.position === 'right') out.position = 'br';
      if (out.position === 'left') out.position = 'bl';
      if (!['br', 'bl', 'tr', 'tl'].includes(out.position)) out.position = 'br';
      if (out.theme === 'dark') out.theme = 'plumDark';
      out.theme = ({ ocean: 'iris', oceanDark: 'irisDark', sage: 'amber', sageDark: 'amberDark' })[out.theme] || out.theme;
      if (!THEMES[out.theme]) out.theme = 'plum';
      if (!LANGS[out.lang]) out.lang = 'en';
      return out;
    } catch {
      return structuredClone(DEFAULTS);
    }
  }

  // Turn "https://www.example.com/path" or "example.com" into "example.com".
  const cleanDomain = input => {
    let s = String(input || '').trim().toLowerCase();
    if (!s) return '';
    try { s = new URL(s.includes('://') ? s : 'https://' + s).hostname; } catch { return ''; }
    s = s.replace(/^www\./, '');
    return /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(s) ? s : '';
  };
  const shopPatterns = domain => [`https://*.${domain}/*`, `http://*.${domain}/*`];

  // ---------- concentration (Parfum vs Eau de Parfum vs Extrait …) ----------
  // Many perfumes exist in several versions with the same name, so the concentration matters.
  const plainText = x => String(x || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[-_]/g, ' ');
  // Words that can follow the concentration at the end of a product name ("… Parfum EDP Spray 100 ml").
  // Gender words count too ("Sauvage Parfum Pour Homme", Sephora's "Parfum Barbati").
  const TRAIL = /^(parfum|perfume|edp|edt|edc|spray|vapo|vaporisateur|vaporizador|natural|sizetoken|pour|for|homme|femme|men|women|man|woman|him|her|herren|damen|uomo|donna|hombre|mujer|barbati|femei|unisex)$/;
  const SIZES = /\d+(?:[.,]\d+)?\s?(?:ml|oz)\b/gi;   // "100 ml" → one "sizetoken" (a bare "1" stays a name word)
  // "Eau de Parfum Intense" (Jean Paul Gaultier, Deloox) is how some shops write the concentration, not part of
  // the name: "Le Male Le Parfum Eau de Parfum Intense" is Le Male Le Parfum. ("Le Male Intense" keeps "Intense".)
  const PHRASES = /\b(extrait de parfum|eau de (?:parfum|toilette) intense|eau de parfum|eau de toilette|eau de cologne)\b/g;
  // "Parfum" only means the concentration when nothing but trailing words follows it:
  // "The Most Wanted Parfum" → yes; "Fugazzi Parfum 1" or "Parfums de Marly" → no.
  const words = t => t.replace(PHRASES, ' edp ').split(/[^a-z0-9.,]+/).filter(Boolean);
  // "Le Parfum" is a name ("Le Male Le Parfum", "Y Le Parfum", "Libre Le Parfum"), not the concentration, and so
  // is "Elixir de Parfum" (Gucci Guilty Elixir de Parfum Pour Homme).
  const isTrailingParfum = (ws, i) => ws[i] === 'parfum' && !['le', 'de'].includes(ws[i - 1]) && ws.slice(i + 1).every(w => TRAIL.test(w));

  function detectConc(text) {
    const t = ' ' + plainText(text).replace(SIZES, ' sizetoken ') + ' ';
    if (/\bextrait\b/.test(t)) return 'extrait';
    if (/(?<!\b(?:le|de) )\bparfum intense\b/.test(t)) return 'parfum';   // "Bottled Elixir - Parfum Intense"
    const ws = t.replace(PHRASES, m => ' ' + m.replace(/ /g, '_') + ' ').split(/[^a-z0-9_.,]+/).filter(Boolean);
    const plain = ws.map(w => (w.includes('_') ? 'edp' : w));
    if (plain.some((w, i) => isTrailingParfum(plain, i))) return 'parfum';
    if (/\beau de parfum\b|\bedp\b/.test(t)) return 'edp';
    if (/\beau de toilette\b|\bedt\b/.test(t)) return 'edt';
    if (/\beau de cologne\b|\bedc\b|\bcologne\b/.test(t)) return 'edc';
    return '';
  }
  function stripConc(text) {
    let s = String(text || '').replace(/(?<!\b(?:le|de) )\bparfum intense\b/gi, ' ').replace(/\b(extrait de parfum|eau de (?:parfum|toilette) intense|eau de parfum|eau de toilette|eau de cologne|extrait|edp|edt|edc|cologne)\b/gi, ' ');
    // Drop a trailing "Parfum" (the concentration) but keep it when it's part of the name ("Parfum 1").
    const parts = s.replace(SIZES, m => m.replace(/\s+/g, '')).split(/\s+/).filter(Boolean);
    const low = parts.map(p => (/^\d+(?:[.,]\d+)?(?:ml|oz)$/i.test(p) ? 'sizetoken' : plainText(p).replace(/[^a-z0-9.,]/g, '')));
    s = parts.filter((p, i) => !(['parfum', 'perfume'].includes(low[i]) && !['le', 'de'].includes(low[i - 1]) && low.slice(i + 1).every(w => !w || TRAIL.test(w)))).join(' ');
    return s.replace(/\s+/g, ' ').trim();
  }
  const CONC_PHRASE = { extrait: 'Extrait de Parfum', parfum: 'Parfum', edp: 'Eau de Parfum', edt: 'Eau de Toilette', edc: 'Cologne' };

  // The theme to use right now: with "automatic" on, the light or dark version of the chosen colour, following the system.
  const resolveTheme = S => {
    if (!S.themeAuto) return S.theme;
    const base = String(S.theme || 'plum').replace(/Dark$/, '');
    const dark = typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
    const key = dark ? base + 'Dark' : base;
    return THEMES[key] ? key : S.theme;
  };
  // Shared prices ("Share prices anonymously"). Only used when the user turns that setting on.
  const API_BASE = 'https://api.fragrancenotes.app';
  // "Own database first": the panel shows the Fragrance Notes database's notes instead of Fragrantica's when
  // at least this many of them are confirmed (two or more shops agree). Fewer: Fragrantica's notes, as before.
  const OWN_MIN_CONFIRMED = 3;
  // The built-in shop a host belongs to ("nl.zalando.nl" → "zalando.nl"), or '' for shops the user added.
  let builtIn = null;
  const builtInShop = host => {
    builtIn ||= new Set(chrome.runtime.getManifest().content_scripts[0].matches
      .map(m => m.replace(/^https?:\/\/\*\./, '').replace(/\/\*$/, '')));
    const parts = String(host || '').toLowerCase().replace(/^www\./, '').split('.');
    for (let i = 0; i < parts.length - 1; i++) if (builtIn.has(parts.slice(i).join('.'))) return parts.slice(i).join('.');
    return '';
  };

  // The country a shop sells to, from its domain ("douglas.de" → "DE"). Used to compare prices only with
  // shops in the same country. '' when unknown (international .com shops not in the list below).
  const TLD_COUNTRY = { nl:'NL', be:'BE', de:'DE', at:'AT', ch:'CH', fr:'FR', it:'IT', es:'ES', pt:'PT', pl:'PL', cz:'CZ', sk:'SK',
    ro:'RO', hu:'HU', hr:'HR', si:'SI', bg:'BG', lt:'LT', lv:'LV', ee:'EE', gr:'GR', se:'SE', dk:'DK', no:'NO', fi:'FI', ie:'IE',
    lu:'LU', uk:'GB', 'co.uk':'GB', au:'AU', 'com.au':'AU', nz:'NZ', 'co.nz':'NZ', ca:'CA', ae:'AE', sa:'SA', sg:'SG', my:'MY',
    jp:'JP', kr:'KR', 'co.kr':'KR', 'com.br':'BR', br:'BR', tr:'TR', 'com.tr':'TR', mx:'MX', 'com.mx':'MX', ua:'UA', rs:'RS', il:'IL', 'co.il':'IL' };
  const COM_COUNTRY = { 'sephora.com':'US', 'ulta.com':'US', 'saks.com':'US', 'saksfifthavenue.com':'US', 'bloomingdales.com':'US',
    'luckyscent.com':'US', 'aedes.com':'US', 'harrods.com':'GB', 'theperfumeshop.com':'GB', 'mecca.com':'AU',
    'galerieslafayette.com':'FR', 'lebonmarche.com':'FR', 'jovoyparis.com':'FR', 'noseparis.com':'FR',
    'perfume.com':'US', 'fragranceoutlet.com':'US', 'bluemercury.com':'US', 'nordstromrack.com':'US', 'flannels.com':'GB',
    'beautybase.com':'GB', 'hondoscenter.com':'GR', 'stockmann.com':'FI', 'beymen.com':'TR', 'gratis.com':'TR', 'myntra.com':'IN', 'purplle.com':'IN' };
  const shopCountry = host => {
    const h = String(host || '').toLowerCase().replace(/^www\./, '');
    for (const [d, c] of Object.entries(COM_COUNTRY)) if (h === d || h.endsWith('.' + d)) return c;
    const p = h.split('.');
    return TLD_COUNTRY[p.slice(-2).join('.')] || TLD_COUNTRY[p[p.length - 1]] || '';
  };
  // Favourites: one small entry per perfume in chrome.storage.sync ("fav:<Fragrantica id>"), so they follow
  // the user to other computers signed in to the same browser account. The perfume details themselves are
  // looked up again when needed (and come from the 14-day cache when recent).
  const FAV_MAX = 400;   // storage.sync allows 512 items in total
  const favs = {
    async all() {
      try {
        const o = await chrome.storage.sync.get(null);
        return Object.keys(o).filter(k => k.startsWith('fav:')).map(k => o[k]).filter(f => f && f.url).sort((a, b) => b.t - a.t);
      } catch { return []; }
    },
    async has(id) {
      if (!id) return false;
      try { return !!(await chrome.storage.sync.get('fav:' + id))['fav:' + id]; } catch { return false; }
    },
    async add(d) {
      const id = (String(d?.url || '').match(/-(\d+)\.html/) || [])[1];
      if (!id) return false;
      if ((await favs.all()).length >= FAV_MAX) return false;
      const entry = { id, url: d.url, name: String(d.title || '').slice(0, 120), img: `https://fimgs.net/mdimg/perfume-thumbs/375x500.${id}.jpg`, t: Date.now() };
      try { await chrome.storage.sync.set({ ['fav:' + id]: entry }); return true; } catch { return false; }
    },
    async remove(id) { try { await chrome.storage.sync.remove(['fav:' + id, 'alert:' + id]); } catch {} }
  };

  // Brands' own websites (the same list as OFFICIAL_SITES in server/catalog.py): there the notes in the product text
  // count as official, so the extension also sends the notes the text names ("mentioned", without a tier).
  const OFFICIAL_SITES = new Set([
    'armani.com', 'armanibeauty.com', 'giorgioarmanibeauty.com', 'dior.fr', 'dior.com', 'chanel.fr', 'chanel.com',
    'guerlain.fr', 'guerlain.com', 'bulgari.com', 'prada.com', 'prada-beauty.com', 'rabanne.com', 'hugoboss.com',
    'gucci.com', 'burberry.com', 'versace.com', 'givenchybeauty.com', 'mugler.com', 'carolinaherrera.com',
    'jeanpaulgaultier.com', 'dolcegabbana.com', 'narcisorodriguez.com', 'valentino.com', 'valentino-beauty.com',
    'ysl.com', 'yslbeauty.com', 'lancome.nl', 'lancome.de', 'lancome.fr', 'lancome.co.uk', 'zara.com',
    'goldfieldandbanks.com', 'etatlibredorange.com', 'profumum.com', 'tomford.com', 'tomfordbeauty.com',
    'acquadiparma.com', 'amouage.com', 'ateliercologne.com', 'bykilian.com', 'kilian.com', 'byredo.com',
    'clivechristian.com', 'creedboutique.com', 'creedfragrances.co.uk', 'diptyqueparis.com', 'exnihilo-paris.com',
    'florislondon.com', 'fredericmalle.com', 'hermes.com', 'jomalone.co.uk', 'jomalone.com', 'juliettehasagun.com',
    'kayali.com', 'lattafa.com', 'louisvuitton.com', 'maisoncrivelli.com', 'maisonfranciskurkdjian.com',
    'marcantoinebarrois.com', 'matiere-premiere.com', 'memoparis.com', 'minnewyork.com', 'nishane.com',
    'ortoparisi.com', 'penhaligons.com', 'sergelutens.com', 'smnovella.com', 'tizianaterenzi.com',
    'viktor-rolf.com', 'xerjoff.com', 'bdkparfums.com', 'bonparfumeur.com', 'essentialparfums.com',
    'initioparfums.com', 'lelabofragrances.com', 'maisonmargiela-fragrances.com', 'mancera-parfums.com',
    'montaleparfums.com', 'parfums-de-marly.com', 'rojaparfums.com',
    'azzaro.com', 'isseymiyakeparfums.com', 'montblanc.com', 'chloe.com', 'esteelauder.com', 'elizabetharden.com', 'cartier.com', 'boucheron.com', 'vancleefarpels.com', 'nasomatto.com', 'lartisanparfumeur.com', 'goutalparis.com', 'aesop.com', 'dsdurga.com', 'imaginaryauthors.com', 'zoologistperfumes.com', 'histoiresdeparfums.com', 'thedifferentcompany.com', 'ormondejayne.com', 'pnicolai.com', 'carnerbarcelona.com', 'fueguia.com', 'rasasi.com', 'arabianoud.com', 'swissarabian.com', 'rituals.com', 'bathandbodyworks.com', 'victoriassecret.com', 'phlur.com', 'ellisbrooklyn.com', 'vilhelmparfumerie.com', 'lancome.it', 'lancome.es', 'lancome.be', 'lancome-usa.com', 'yslbeauty.co.uk', 'yslbeauty.fr', 'yslbeautyus.com', 'giorgioarmanibeauty-usa.com'
  ]);
  const officialSite = host => OFFICIAL_SITES.has(builtInShop(host));

  // The first sentence of a note description (the note pop-ups show only that; the full text is on the website).
  const firstSentence = s => (String(s || '').trim().match(/^.+?[.!?](?=\s|$)/) || [String(s || '').trim()])[0];
  globalThis.FN = { firstSentence, API_BASE, OWN_MIN_CONFIRMED, IS_FIREFOX, REVIEW_URL, favs, builtInShop, officialSite, shopCountry, resolveTheme, detectConc, stripConc, CONC_PHRASE, cleanDomain, shopPatterns, DEFAULTS, SECTION_GROUPS, SECTION_LABELS, THEMES, LANGS, LANG_HOSTS, t, loadSettings: load };
})();
