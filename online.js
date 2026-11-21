// Live price comparison via Google Shopping (all countries in Settings).
// Opens the Shopping results for the perfume in a background tab, reads the offers
// (shop, price, size or unit price) and keeps only listings of this exact perfume.
// Loaded by background.js (importScripts).
(() => {
  const TTL = 6 * 3600e3;
  const inFlight = new Map();

  const norm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ').trim();
  const CONC_WORDS = /\b(extrait de parfum|eau de parfum|eau de toilette|eau de cologne|extrait|edp|edt|edc|parfum|perfume|spray)\b/g;
  // Words that may appear in a listing without making it a different product.
  const FILLER = new Set(['vapo', 'vaporisateur', 'vaporizador', 'natural', 'unisex', 'men', 'women', 'man', 'woman', 'homme', 'femme',
    'pour', 'for', 'heren', 'dames', 'herren', 'damen', 'voor', 'ml', 'de', 'eau', 'and', 'new', 'nieuw', 'neu', 'original', 'origineel',
    'geur', 'geuren', 'fragrance', 'duft', 'deal', 'sale', 'by', 'van', 'von']);
  const SIZE = /(\d+(?:[.,]\d+)?)\s?ml\b/i;

  // brand + name from a Fragrantica URL (any language site): /perfume/Creed/Aventus-9828.html
  function fromUrl(url) {
    const m = String(url).match(/\/([^/]+)\/([^/]+)-(\d+)\.html/);
    if (!m) return null;
    const words = x => decodeURIComponent(x).replace(/-/g, ' ');
    return { brand: words(m[1]), name: words(m[2]), id: m[3] };
  }

  // Is this listing the same perfume (not a flanker, hair mist or gift set)?
  function sameProduct(title, brand, name, conc) {
    if (/\b(tester|set|geschenkset|giftset|cadeauset|coffret|sample|proefje|hair|haar|body|lotion|shower|deo|deodorant|candle|kaars|refill)\b/i.test(title)) return false;
    const itemConc = FN.detectConc(title);
    if (conc && itemConc && itemConc !== conc) return false;
    let t = ' ' + norm(title.replace(new RegExp(SIZE.source, 'gi'), ' ')).replace(CONC_WORDS, ' ') + ' ';
    const need = [...norm(brand).split(' '), ...norm(name).replace(CONC_WORDS, ' ').split(' ')].filter(Boolean);
    for (const w of need) {
      const re = new RegExp(`(^| )${w}(?= |$)`, 'g');
      if (!re.test(t)) return false;
      t = t.replace(re, ' ');                          // brand is sometimes repeated: remove every copy
    }
    const left = t.split(' ').filter(w => w && !FILLER.has(w) && !/^\d+$/.test(w));
    return left.length === 0;
  }

  // "1.234,56" / "1,234.56" / "170,00" → number
  const toNum = s => {
    s = String(s).replace(/[^\d.,]/g, '');
    const last = Math.max(s.lastIndexOf(','), s.lastIndexOf('.'));
    if (last >= 0 && s.length - last - 1 <= 2) return parseFloat(s.slice(0, last).replace(/[.,]/g, '') + '.' + s.slice(last + 1));
    return parseFloat(s.replace(/[.,]/g, ''));
  };
  const CUR = { '€': 'EUR', '£': 'GBP', '$': 'USD', 'zł': 'PLN', 'kr': 'SEK', 'Kč': 'CZK', 'lei': 'RON', 'Ft': 'HUF', 'CHF': 'CHF', '₺': 'TRY' };
  const curOf = s => { for (const [k, v] of Object.entries(CUR)) if (s.includes(k)) return v; return ''; };

  // Size in ml, only when the listing's title says it. Unit prices ("€2,200.00/1kg") are not used:
  // shops often fill them in wrong (Skins lists a 50 ml bottle as 100 g).
  function sizeOf(card) {
    const sizes = [...new Set([...card.title.matchAll(new RegExp(SIZE.source, 'gi'))].map(m => parseFloat(m[1].replace(',', '.'))))];
    return sizes.length === 1 ? sizes[0] : 0;      // "2ml, 5ml, 10ml" sample packs: unclear, skip
  }

  // ---- runs inside the Google Shopping tab ----
  async function readShoppingInPage(word) {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const PRICE = /^(?:[€£$]|CHF|EUR|USD|GBP)?\s?\d[\d.,   ]*\s?(?:[€£$]|zł|kr|Kč|lei|Ft|CHF|₺)?$/;
    const hasCur = s => /[€£$]|zł|kr|Kč|lei|Ft|CHF|₺/.test(s);
    const NOT_SELLER = /^(\+|&|·|\()|pre-?owned|\/\s?\d*\s?(kg|l|ml)\b|free|gratis|kostenlos|gratuit|delivery|verzend|versand|livraison|shipping|returns?|retour|used|tweedehands|gebraucht|occasion|usato|usado|refurb|sale|deal|korting|rabatt|%|\(\d/i;
    const USED = /used|pre-?owned|tweedehands|gebruikt|gebraucht|d'occasion|usato|usado|refurb|marktplaats|vinted|ebay/i;
    word = String(word || '').toLowerCase();
    let cards = [];
    for (let i = 0; i < 40; i++) {
      if (/consent\.google|sorry\/index/.test(location.href)) return { error: /sorry/.test(location.href) ? 'captcha' : 'consent' };
      const els = [...document.querySelectorAll('div,li')].filter(e => {
        const t = e.innerText || '';
        return t.length < 400 && t.toLowerCase().includes(word) && hasCur(t) && /\d/.test(t);
      });
      const minimal = els.filter(e => !els.some(o => o !== e && e.contains(o)));
      const roots = [...new Set(minimal.map(e => {
        let c = e;
        while (c.parentElement && (c.parentElement.innerText || '').length < 350) c = c.parentElement;
        return c;
      }))];
      cards = roots.map(c => {
        const lines = (c.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
        const pi = lines.findIndex(l => PRICE.test(l) && hasCur(l));
        if (pi < 1) return null;
        const after = lines.slice(pi + 1);
        const seller = after.find(l => !NOT_SELLER.test(l) && !PRICE.test(l) && l.length < 50);
        return seller ? {
          title: (pi > 1 ? lines.slice(0, pi).filter(l => !/%|^sale\b|korting|rabatt|^deal\b|^new\b|^nieuw\b/i.test(l)) : lines.slice(0, pi)).join(' '), price: lines[pi], seller,
          unit: after.find(l => /\/\s?\d*\s?(kg|l|ml)\b/i.test(l)) || '',
          ship: after.find(l => /^\+/.test(l)) || '',
          used: USED.test(lines.join(' ')), ad: !!c.closest('.pla-unit'),
          link: (c.querySelector('a[href*="/goto?url="]') || c.closest('a[href*="/goto?url="]'))?.href || ''
        } : null;
      }).filter(Boolean);
      if (cards.length >= 6 || (cards.length && i > 12)) break;
      if (i === 8) window.scrollTo(0, 2500);    // some results load on scroll
      await sleep(250);
    }
    return { cards };
  }

  // ---- links straight to the shop ----
  // Google doesn't give the shops' own links, so for each offer we look the product up on that
  // shop's website with Bing (site:shop.nl …) and link to the first product page found there.
  const shopKey = s => String(s || '').toLowerCase().replace(/^www\./, '').replace(/\.(co\.uk|com\.au|com\.tr|[a-z]{2,3})$/, '')
    .replace(/\s(nl|be|de|fr|uk|es|it|com)$/, '').replace(/^(de|the|la|le)\s+/, '').replace(/[^a-z0-9]/g, '');
  async function knownDomains() {
    const fromManifest = (chrome.runtime.getManifest().content_scripts || []).flatMap(c => c.matches || [])
      .map(m => (m.match(/^https?:\/\/\*\.([^/]+)\//) || [])[1]).filter(Boolean);
    const { customShops = [] } = await chrome.storage.sync.get('customShops').catch(() => ({}));
    return [...new Set([...fromManifest, ...customShops])];
  }
  function shopDomain(seller, domains, gl) {
    const s = String(seller || '').trim().toLowerCase();
    if (/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(s)) return s.replace(/^www\./, '');      // "Notino.nl"
    const k = shopKey(s);
    const hits = domains.filter(d => shopKey(d) === k);
    return hits.find(d => d.endsWith('.' + gl)) || hits.find(d => d.endsWith('.com')) || hits[0] || '';
  }
  // Google's own "go to shop" link when the listing has one (it redirects to the shop's product page);
  // otherwise Google's "I'm feeling lucky" limited to the shop's website.
  const luckyLink = (domain, words) => `https://www.google.com/search?btnI=1&q=${encodeURIComponent((domain ? `site:${domain} ` : '') + words)}`;

  async function resolveLucky(url) {
    try {
      const r = await fetch(url, { credentials: 'include' });
      const final = new URL(r.url);
      if (!/(^|\.)google\./.test(final.hostname)) return r.url;
      const q = final.searchParams.get('q') || final.searchParams.get('url');
      if (q && /^https?:\/\//.test(q)) return q;
      const m = (await r.text()).match(/href="(https?:\/\/(?![^"]*google\.)[^"]+)"/);
      return m ? m[1].replace(/&amp;/g, '&') : '';
    } catch { return ''; }
  }

  async function lookupOnline(fragUrl, conc, country) {
    const p = fromUrl(fragUrl);
    if (!p) return { unsupported: true };
    conc = FN.detectConc(p.name) || conc || '';
    const c = FN.COUNTRIES[country] || FN.COUNTRIES.NL;
    const query = `${p.brand} ${p.name.replace(CONC_WORDS, ' ')} ${conc ? FN.CONC_PHRASE[conc] : ''}`.replace(/\s+/g, ' ').trim();
    const search = `https://www.google.com/search?udm=28&gl=${c.gl}&hl=en&q=${encodeURIComponent(query)}`;
    const tab = await openHidden(search);
    try {
      await waitForLoad(tab.id).catch(() => {});
      const word = norm(p.name.replace(CONC_WORDS, ' ')).split(' ').sort((a, b) => b.length - a.length)[0] || norm(p.brand);
      let res = null;
      for (let i = 0; i < 3 && !res; i++) {
        const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', func: readShoppingInPage, args: [word] }).catch(() => [null]);
        res = r?.result || null;
        if (!res) await new Promise(r => setTimeout(r, 1500));
      }
      if (!res) return { error: 'blocked', search };
      if (res.error) return { error: res.error, search };
      const offers = [];
      const domains = await knownDomains();
      for (const card of res.cards) {
        if (card.used) continue;
        const price = toNum(card.price);
        const ml = price > 0 ? sizeOf(card) : 0;
        if (!ml || !sameProduct(card.title, p.brand, p.name, conc)) continue;
        const ship = card.ship ? toNum(card.ship) : 0;
        offers.push({ seller: card.seller, price, ml, currency: curOf(card.price) || 'EUR', shipping: ship || 0, title: card.title,
          domain: shopDomain(card.seller, domains, c.gl), link: card.link });
      }
      // Drop suspicious prices far below the rest (wrong size in the title, samples, fakes).
      if (offers.length >= 3) {
        const pers = offers.map(o => o.price / o.ml).sort((a, b) => a - b);
        const median = pers[Math.floor(pers.length / 2)];
        for (let i = offers.length - 1; i >= 0; i--) if (offers[i].price / offers[i].ml < median * 0.4) offers.splice(i, 1);
      }
      const words = `${p.brand} ${p.name.replace(CONC_WORDS, ' ')}`.replace(/\s+/g, ' ').trim();
      // The shop's real product page: Google's "I'm feeling lucky" limited to that shop's website.
      // (Lucky shows a "you're being redirected" page, so the real address is read from it here.)
      // Fallbacks: Google's own "go to shop" link from the listing, then the lucky link itself.
      offers.sort((a, b) => a.price / a.ml - b.price / b.ml);   // the panel shows each shop's cheapest per ml
      const shown = new Set();
      await Promise.all(offers.filter(o => o.domain && !shown.has(o.domain) && shown.add(o.domain)).slice(0, 12).map(async o => {
        const real = await resolveLucky(luckyLink(o.domain, `${words} ${o.ml} ml`));
        if (real && new URL(real).hostname.replace(/^www\./, '').endsWith(o.domain)) o.url = real;
      }));
      for (const o of offers) if (!o.url) o.url = o.link || luckyLink(o.domain, o.domain ? `${words} ${o.ml} ml` : `${o.seller} ${o.title}`);
      offers.forEach(o => { delete o.link; delete o.domain; });
      return { offers, search: search.replace('hl=en', `hl=${c.hl}`), source: 'google' };
    } finally {
      closeHidden(tab.id);
    }
  }

  async function online(fragUrl, conc, country, force) {
    const p = fromUrl(fragUrl);
    if (!p) return { unsupported: true };
    const key = `o8:${country}:${p.id}:${conc || ''}`;
    if (!force) {
      const c = (await chrome.storage.local.get(key))[key];
      if (c && Date.now() - c.t < TTL) return { ...c.data, cached: true };
    }
    if (inFlight.has(key)) return inFlight.get(key);
    const job = lookupOnline(fragUrl, conc, country).then(async data => {
      if (!data.error) await chrome.storage.local.set({ [key]: { t: Date.now(), data } });
      return data;
    }).catch(e => ({ error: e.message })).finally(() => inFlight.delete(key));
    inFlight.set(key, job);
    return job;
  }

  globalThis.FN_ONLINE = { online, shopDomain, luckyLink, sameProduct, sizeOf, fromUrl, toNum, readShoppingInPage };
})();
