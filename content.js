// Detects the perfume on a shop page and shows a floating Fragrantica panel.
(() => {
  if (window.__fnLoaded) return;
  window.__fnLoaded = true;

  // "Perfume" in the shop languages we support (Latin-script words use word boundaries).
  const FRAG_RE = /\b(parfums?|perfumes?|perfumy|perfumy|profum[oi]|parf[ée]m|parf[üu]m|eau de|cologne|colonia|edp|edt|extrait|fragrances?|fragancia|fragranza|geur|duft|doft|tuoksu|illat|koku|vůně|zapach)\b|духи|парфюм|туалетн|парфум|άρωμα|香水|フレグランス|향수|عطر|בושם/i;

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

  // Name without brand, sizes, packaging words and concentration (that is added back separately).
  function cleanName(name, brand) {
    let n = withoutBrand(trimDescription(name), brand);
    n = FN.stripConc(n)
      .replace(/\b\d+([.,]\d+)?\s?(ml|oz|g)\b/gi, ' ')
      .replace(/\b(spray|vapo|vaporisateur|vaporizador|vaporizzatore|zerst[aä]uber|natural spray|navulling|refill|nachf[uü]llung|tester|for (wo)?men|pour (homme|femme)|unisex|limited edition)\b/gi, ' ')
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
      if (/[\p{L}]{3,}/u.test(cl)) { name = c; cleaned = cl; break; }
    }
    // Concentration: from the chosen name first, then the other sources (and the product's offers).
    const concSources = [name, ...candidates, ...((p?.offers && [].concat(p.offers).map(o => o?.name)) || [])];
    let conc = '';
    for (const s of concSources) { conc = FN.detectConc(withoutBrand(trimDescription(s || ''), brand)); if (conc) break; }

    // Also look at the size options and breadcrumbs ("Parfum › Herrendüfte") for the word "perfume".
    const offerNames = (p?.offers && [].concat(p.offers).map(o => o?.name || '').join(' ')) || '';
    const crumbs = [...document.querySelectorAll('nav[aria-label*="breadcrumb" i], [class*="breadcrumb" i], [itemtype$="BreadcrumbList"]')]
      .slice(0, 2).map(e => e.textContent).join(' ').slice(0, 400);
    const blob = `${brand} ${candidates.join(' ')} ${p?.category || ''} ${offerNames} ${crumbs} ${document.title}`;
    // Only real product pages count (not the homepage or category pages).
    const isProduct = !!p || !!document.querySelector('meta[property="og:type"][content*="product" i]');
    const isFragrance = !!name && FRAG_RE.test(blob);
    return {
      query: [brand, cleaned, FN.CONC_PHRASE[conc] || ''].filter(Boolean).join(' ').trim(),
      conc,
      isProduct,
      isFragrance,
      show: isProduct && isFragrance
    };
  }

  // ---------- price per ml ----------
  // Sizes and prices: first from the shop's product data (offers per size), otherwise from the
  // page text, where each size option usually sits in its own element with its price.
  const SIZE_RE = /(\d+(?:[.,]\d+)?)\s?(?:ml|mL|ML)\b/;
  const CUR = '€|£|\\$|EUR|USD|GBP|CHF|zł|PLN|kr|SEK|DKK|NOK|Kč|CZK|lei|RON|Ft|HUF|₺|TRY|₽|RUB|₴|UAH|AUD|CAD|JPY|¥|₩';
  const NUM = `\\d{1,3}(?:[ .,'\\u00a0]\\d{3})*(?:[.,]\\d{1,2})?|\\d+(?:[.,]\\d{1,2})?`;
  const PRICE_RE = new RegExp(`(?:(${CUR})\\s?(${NUM}))|(?:(${NUM})\\s?(${CUR}))`, 'g');
  // Unit prices such as "100 ml / € 51,41", "€ 149,98 / 100 ml" or "2.545,00 € / 1L" — removed before reading sizes.
  const PER = `(?:\\/|per|pro|je|par|za|за|le|la)`;
  const UNIT = `(?:1|10|100)\\s?ml|1\\s?(?:l|L|ltr|liter|litre|litro)\\b|(?:l|L|liter|litre|litro)\\b`;
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
      if (!(ml > 0 && ml <= 1000 && price > 0)) return;
      const prev = m.get(ml);
      if (!prev || price < prev.price) m.set(ml, { ml, price, currency: currency || 'EUR' });
    };

    // 1) Structured data: one offer per size (Sephora microdata, many JSON-LD shops).
    const structured = new Map();
    try {
      const p = readProduct();
      const offers = [];
      const pushOffers = (o, fallbackName) => [].concat(o || []).forEach(x => x && offers.push({ ...x, _name: x.name || fallbackName }));
      if (p) {
        pushOffers(p.offers, `${p.size || ''} ${p.name || ''}`);
        [].concat(p.hasVariant || []).forEach(v => pushOffers(v.offers, `${v.size || ''} ${v.name || ''}`));
      }
      for (const o of offers) {
        const size = String(o._name || '').match(SIZE_RE);
        const price = parseFloat(o.price ?? o.lowPrice);
        if (size) add(structured, toNum(size[1]), price, o.priceCurrency);
      }
    } catch {}
    if (structured.size >= 2) return [...structured.values()].sort((a, b) => a.ml - b.ml).slice(0, 8);

    // 2) Page text.
    try {
      // "151 , 99" (cents in a separate element) → "151,99"
      const textOf = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').replace(/(\d)\s?([.,])\s?(\d{2})(?!\d)/g, '$1$2$3').replace(UNIT_PRICE_RE, ' ');
      // Some shops (e.g. Deloox) show prices without a currency sign: "onze prijs: 151,99".
      // Those only count outside product cards for other products (related items, carousels).
      const pageCur = [...structured.values()][0]?.currency || document.querySelector('[itemprop="priceCurrency"]')?.getAttribute('content') || 'EUR';
      const OTHER_PRODUCTS = '[class*="related" i],[class*="recommend" i],[class*="productline" i],[class*="carousel" i],[class*="slider" i],[class*="upsell" i],[class*="cross-sell" i],[class*="crosssell" i],header,footer,nav,aside';
      const here = location.pathname;
      const linksElsewhere = e => [e.closest('a[href]'), ...e.querySelectorAll('a[href]')].some(a => {
        try { return a && new URL(a.href, location.href).pathname !== here; } catch { return false; }
      });
      const barePrices = t => {
        const out = [...t.matchAll(BARE_PRICE_RE)].map(m => toNum(m[1]));
        return out.length ? out : [...t.matchAll(DECIMAL_RE)].map(m => toNum(m[1]));
      };
      const pricesIn = (e, t) => {
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
    for (const v of structured.values()) add(map, v.ml, v.price, v.currency);
    return [...map.values()].sort((a, b) => a.ml - b.ml).slice(0, 8);
  }

  // ---------- UI ----------
  const { CSS, flower, themeCss, renderBody, panelHtml, esc, localizeChrome } = FN_UI;

  const host = document.createElement('div');
  host.setAttribute('data-fn-host', '');
  host.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;display:flex;flex-direction:column;align-items:flex-end;gap:8px;';
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
    if (!S.enabled || !current.show || !(S.autoSearch || S.autoOpen)) return;
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
    if (res.error) return renderError(res, query);
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
  let pricesOpen = false;
  const perfumeId = url => (String(url || '').match(/-(\d+)\.html/) || [])[1];
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
    const prices = current.isProduct ? readPrices() : [];
    const elsewhere = S.sections.elsewhere ? await seenPrices(d, prices) : [];
    if (lastRender?.data !== d) return;    // a newer render started meanwhile
    const opts = { cached, query, prices: S.sections.perMl ? prices : [], elsewhere, othersAll: false, host: location.hostname, pricesOpen };
    const paint = () => {
      body.innerHTML = renderBody(d, S, opts);
      body.querySelector('.refresh')?.addEventListener('click', () => lookup(query, true));
      body.querySelector('.more')?.addEventListener('click', () => { opts.othersAll = true; paint(); });
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
    if (!panel.hidden) askOpinions();
    else { const prev = pendingWork; pendingWork = () => { prev?.(); askOpinions(); }; }
    pricesOpen = opts.pricesOpen = false;   // the other-shops list always starts closed
    paint();
  }

  // ---------- keyboard shortcut (set in Settings; empty = off) ----------
  const comboOf = e => {
    const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(k)) return '';
    return [e.ctrlKey && 'Ctrl', e.altKey && 'Alt', e.shiftKey && 'Shift', e.metaKey && 'Meta', e.code?.startsWith('Key') ? e.code.slice(3) : e.code?.startsWith('Digit') ? e.code.slice(5) : k]
      .filter(Boolean).join('+');
  };
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
