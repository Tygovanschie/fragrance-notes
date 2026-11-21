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
    accStyle: 'bars',      // accords as 'bars' or one colour 'strip'
    themeAuto: false,      // follow the system's light/dark mode (uses the light or dark version of the chosen colour)
    lang: 'en',            // Fragrantica language site to read from
    shortcut: '',          // keyboard shortcut to show/hide the panel, e.g. "Alt+F" (empty = none)
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
      name: 'Plum', bg: '#fffdfb', fg: '#231a22', muted: '#8a7a85', label: '#8a6b80',
      head: '#2b1d2e', headFg: '#f6e9f2', accent: '#8a3f6f', soft: '#c58bb0',
      chip: '#f4e9f0', card: '#faf4f8', border: '#eee3ea', input: '#ffffff', inputBorder: '#d9c9d4'
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
  const PANEL_KEYS = ['title', 'search', 'placeholder', 'notes', 'priceValue', 'data', 'cached', 'refresh', 'looking', 'noNotes', 'dupes', 'dupe', 'perMl', 'best', 'elsewhere', 'didYouMean', 'notFound', 'pros', 'cons', 'prosCons', 'agree', 'rating', 'typeHint', 'reloaded', 'blocked', 'unreadable', 'failed', 'openFrag', 'notAffiliated'];
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
  const PHRASES = /\b(extrait de parfum|eau de parfum|eau de toilette|eau de cologne)\b/g;
  // "Parfum" only means the concentration when nothing but trailing words follows it:
  // "The Most Wanted Parfum" → yes; "Fugazzi Parfum 1" or "Parfums de Marly" → no.
  const words = t => t.replace(PHRASES, ' edp ').split(/[^a-z0-9.,]+/).filter(Boolean);
  const isTrailingParfum = (ws, i) => ws[i] === 'parfum' && ws.slice(i + 1).every(w => TRAIL.test(w));

  function detectConc(text) {
    const t = ' ' + plainText(text).replace(SIZES, ' sizetoken ') + ' ';
    if (/\bextrait\b/.test(t)) return 'extrait';
    const ws = t.replace(PHRASES, m => ' ' + m.replace(/ /g, '_') + ' ').split(/[^a-z0-9_.,]+/).filter(Boolean);
    const plain = ws.map(w => (w.includes('_') ? 'edp' : w));
    if (plain.some((w, i) => isTrailingParfum(plain, i))) return 'parfum';
    if (/\beau de parfum\b|\bedp\b/.test(t)) return 'edp';
    if (/\beau de toilette\b|\bedt\b/.test(t)) return 'edt';
    if (/\beau de cologne\b|\bedc\b|\bcologne\b/.test(t)) return 'edc';
    return '';
  }
  function stripConc(text) {
    let s = String(text || '').replace(/\b(extrait de parfum|eau de parfum|eau de toilette|eau de cologne|extrait|edp|edt|edc|cologne)\b/gi, ' ');
    // Drop a trailing "Parfum" (the concentration) but keep it when it's part of the name ("Parfum 1").
    const parts = s.replace(SIZES, m => m.replace(/\s+/g, '')).split(/\s+/).filter(Boolean);
    const low = parts.map(p => (/^\d+(?:[.,]\d+)?(?:ml|oz)$/i.test(p) ? 'sizetoken' : plainText(p).replace(/[^a-z0-9.,]/g, '')));
    s = parts.filter((p, i) => !(['parfum', 'perfume'].includes(low[i]) && low.slice(i + 1).every(w => !w || TRAIL.test(w)))).join(' ');
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
  globalThis.FN = { resolveTheme, detectConc, stripConc, CONC_PHRASE, cleanDomain, shopPatterns, DEFAULTS, SECTION_GROUPS, SECTION_LABELS, THEMES, LANGS, LANG_HOSTS, t, loadSettings: load };
})();
