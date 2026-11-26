// Chrome/Edge run this as a service worker (loads settings.js here); Firefox runs it as an event page
// with settings.js listed before it in the manifest.
if (typeof importScripts === 'function') importScripts('settings.js', 'i18n-settings.js');

// Service worker: finds the Fragrantica page for a perfume, loads it in a background
// tab, reads the data Fragrantica's own page script decodes, then closes the tab.

const TTL = 14 * 24 * 60 * 60 * 1000; // cache results for 14 days
const keyFor = (q, lang) => `c12:${lang}:` + q.trim().toLowerCase(); // bump prefix to invalidate old cache

// ---------- search (Bing) ----------
function decodeBing(u) {
  // Bing wraps results as /ck/a?...&u=a1<base64url of the real URL>
  try {
    let b = u.replace(/^a1/, '').replace(/-/g, '+').replace(/_/g, '/');
    while (b.length % 4) b += '=';
    return atob(b);
  } catch { return null; }
}

// Houses known for affordable alternatives of famous perfumes (lower-case, accents removed).
const DUPE_HOUSES = [
  'armaf', 'afnan', 'lattafa', 'lattafa perfumes', 'al haramain perfumes', 'rasasi', 'maison alhambra',
  'zara', 'dua fragrances', 'alexandria fragrances', 'french avenue', 'fragrance world', 'paris corner',
  'ard al zaafaran', 'khadlaj', 'rayhaan', 'emper', 'dossier', 'oakcha', 'montagne parfums', 'alt fragrances',
  'pendora scents', 'milestone perfumes', 'le chameau', 'sapil', 'nabeel', 'swiss arabian', 'gulf orchid',
  'arabiyat prestige', 'flavia', 'fragrance one', 'perfume lounge', 'bharara', 'jean lowe', 'nusuk',
  'zimaya', 'riiffs', 'dumont', 'fragrance du bois', 'al wataniah', 'my perfumes', 'ahmed al maghribi',
  'asdaaf', 'orientica', 'reyane tradition', 'cuba paris', 'adyan', 'emir', 'aurora scents'
];

const PERFUME_URL = /^https?:\/\/(?:www\.)?fragrantica\.com\/perfume\/([^/]+)\/([^/?#]+)-\d+\.html/;

function fragranticaUrls(html) {
  const urls = [];
  for (const m of html.matchAll(/[?&](?:amp;)?u=(a1[A-Za-z0-9_-]+)/g)) {
    const d = decodeBing(m[1]);
    if (d) urls.push(d);
  }
  for (const m of html.matchAll(/https?:\/\/(?:www\.)?fragrantica\.com\/perfume\/[^"'&\s<>]+/g)) urls.push(m[0]);
  return [...new Set(urls.map(u => u.replace(/^http:/, 'https:').split('#')[0]).filter(u => PERFUME_URL.test(u)))];
}

// Words of a name, compared without accents and case. "N°5" / "Nº 5" / "No. 5" all become "no 5".
// Single letters count too (YSL "Y", "L'Homme"), so they must match like any other word.
const tokens = s => String(s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  .replace(/\bn\s*[°º]\s*|\bno\.\s*(?=\d)/g, 'no ')
  .split(/[^a-z0-9]+/).filter(Boolean);

// Gender words. They tell versions apart ("Gucci Guilty Pour Homme" vs the women's "Gucci Guilty"), but
// many names don't carry one, so they're scored separately instead of as name words.
const MALE = /\b(pour homme|for men|for him|homme|uomo|hombre|herren|men|man)\b/;
const FEMALE = /\b(pour femme|for women|for her|femme|donna|mujer|damen|women|woman)\b/;
const genderOf = s => { const t = ' ' + s.toLowerCase().replace(/-/g, ' ') + ' '; return FEMALE.test(t) ? 'f' : MALE.test(t) ? 'm' : ''; };
const GENDER_WORDS = new Set(['pour', 'for', 'homme', 'femme', 'him', 'her', 'men', 'man', 'women', 'woman', 'uomo', 'donna', 'hombre', 'mujer', 'herren', 'damen']);

// Score a Fragrantica URL against the query.
// - Every word of the query's name should be in the candidate. A missing word costs a lot: it's usually
//   what tells a flanker apart ("Stronger With You Absolutely" is not "Stronger With You Parfum").
// - Extra words in the candidate's name (flankers like "Intense", "Elixir") cost a little.
// - Concentration (Parfum / Eau de Parfum / Extrait / Eau de Toilette): a match helps, a different one
//   costs. A candidate without one in its name is neutral (Fragrantica often leaves it out).
// - Gender: the opposite gender costs a lot, the same one helps a little.
// vocab (optional): every word of every candidate found. A query word that no candidate has at all is
// probably shop noise ("Refill", "Coffret", a slogan) and is then ignored instead of costing points.
function score(url, query, vocab = null) {
  const [, designer, name] = url.match(PERFUME_URL);
  let nameText = decodeURIComponent(name).replace(/-/g, ' ');
  const qConc = FN.detectConc(query);
  // A shop's "MYSLF Parfum" is Fragrantica's "MYSLF Le Parfum": when the query is the Parfum version and doesn't
  // say "Le Parfum" itself, a candidate's "Le Parfum" is its concentration, not two extra name words. (When the
  // query has "Le Parfum", as in "Le Male Le Parfum", it stays part of the name.)
  const leParfum = qConc === 'parfum' && !/\ble parfum\b/i.test(query) && /\ble parfum\b/i.test(nameText);
  if (leParfum) nameText = nameText.replace(/\ble parfum\b/i, ' ');
  const cConc = leParfum ? 'parfum' : FN.detectConc(nameText);
  const qGender = genderOf(query), cGender = genderOf(nameText);
  const words = s => tokens(FN.stripConc(s)).filter(t => !GENDER_WORDS.has(t));
  const designerT = new Set(tokens(decodeURIComponent(designer).replace(/-/g, ' ')));
  const nameT = words(nameText);
  const nameSet = new Set(nameT);
  let q = new Set(words(query));
  if (vocab) {
    const known = [...q].filter(t => vocab.has(t));
    if (known.length) q = new Set(known);
  }
  let hits = 0, missing = 0;
  q.forEach(t => {
    if (nameSet.has(t) || designerT.has(t)) hits++;
    else missing++;
  });
  const extra = nameT.filter(t => !q.has(t) && !designerT.has(t)).length;
  // A different house is almost always a clone or a "smells like" (Armaf for Creed): when the query names
  // the brand, the candidate's house must share a word with it.
  const brandHit = [...designerT].some(t => q.has(t));
  let s = hits / Math.max(q.size, 1) - missing * 0.3 - extra * 0.15;
  if (qConc && cConc) s += cConc === qConc ? 0.2 : -0.4;     // right / wrong version
  else if (cConc && !qConc) s -= 0.2;                        // query has no version: prefer the plain one
  else if (!cConc && (!qConc || qConc === 'edt')) s += 0.1;  // the plain name is usually the EDT/original
  if (qGender && cGender) s += cGender === qGender ? 0.15 : -0.6;
  else if (!qGender && cGender) s -= 0.05;
  if (!brandHit) s -= 0.35;
  // "Eau de Toilette/Parfum Intense" in the query: often just how a shop writes the concentration (Le Male Le
  // Parfum), sometimes its own version (Gucci Guilty Eau de Toilette Intense Pour Homme). So a candidate with
  // "Intense" wins, but one without it isn't punished.
  const qIntense = /\bintense\b/i.test(query), cIntensePhrase = /\beau de (parfum|toilette) intense\b/i.test(nameText);
  if (/\beau de (parfum|toilette) intense\b/i.test(query) && /\bintense\b/i.test(nameText)) {
    s += 0.3;
    if (!cIntensePhrase) s += 0.15;   // undo the extra-word cost
  } else if (cIntensePhrase && !qIntense) {
    s -= 0.3;   // stripConc hides "Intense" in the candidate, so a plain EDT page would otherwise pick it
  }
  return s;
}

async function bing(q) {
  const r = await fetch('https://www.bing.com/search?setlang=en&q=' + encodeURIComponent(q), { credentials: 'include' });
  if (!r.ok) return [];
  return fragranticaUrls(await r.text());
}

// Short scent description of a note ("Odor profile: citrusy, bitter & tart…") from its Fragrantica page.
async function noteInfo(url) {
  if (!/^https:\/\/[^/]*fragrantica\.[^/]+\/[^/]+\/[^/]+-\d+\.html$/.test(url || '')) return { error: 'bad' };
  const key = 'n2:' + url;
  const c = (await chrome.storage.local.get(key))[key];
  if (c) return c;
  let html = '';
  try { const r = await fetch(url, { credentials: 'include' }); if (r.ok) html = await r.text(); } catch {}
  const h1 = html.indexOf('<h1');
  if (h1 < 0) return { error: 'blocked' };
  // The note page starts with: name, Latin name, then "Other names: …", "Group: …", "Odor profile: …"
  // (labels in the site's language). Read those "label: value" lines.
  const decode = x => x.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"')
    .replace(/&#0?39;|&rsquo;/g, '’').replace(/&#(\d+);/g, (m, n) => String.fromCharCode(+n));
  const lines = decode(html.slice(h1, h1 + 12000)
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, '')
    .replace(/<\/(p|div|h1|h2|h3|li|span)>|<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, ''))
    .split('\n').map(l => l.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 14);
  const latin = lines[1] && !lines[1].includes(':') && lines[1].length < 60 ? lines[1] : '';
  const facts = lines.slice(1).filter(l => /^[^:]{2,30}:\s+\S/.test(l)).slice(0, 3).map(l => {
    const i = l.indexOf(':');
    let v = l.slice(i + 1).trim();
    if (v.length > 260) v = v.slice(0, 250).replace(/\s+\S*$/, '') + '…';
    return { label: l.slice(0, i).trim(), text: /^[A-Z\s,&]+$/.test(v) ? v.charAt(0) + v.slice(1).toLowerCase() : v };
  });
  const res = { latin, facts, url };
  if (facts.length) await chrome.storage.local.set({ [key]: res });
  return res;
}

// ---------- pages read out of sight ----------
// Pages that have to run in a real browser tab (Fragrantica) are opened in one small
// minimized window instead of next to the user's own tabs, and closed as soon as they've been read.
// The window itself closes again when it has been idle for a little while.
// No placeholder page: the window opens with the first page and closes by itself when its last page
// is closed, so nothing is left behind (even if Chrome stops this background script in between).
let hiddenWin = null;          // Promise<windowId | null>
async function openHidden(url) {
  if (hiddenWin) {
    const id = await hiddenWin;
    if (id) {
      try { return await chrome.tabs.create({ windowId: id, url, active: false }); } catch {}   // window may have just closed
    }
  }
  // Firefox doesn't accept focused:false; a minimized window doesn't take focus there anyway.
  const opts = FN.IS_FIREFOX ? { url, state: 'minimized', type: 'normal' } : { url, state: 'minimized', focused: false, type: 'normal' };
  const made = chrome.windows.create(opts).catch(() => null);
  hiddenWin = made.then(w => w?.id || null);
  const w = await made;
  if (w?.tabs?.[0]) {
    chrome.storage.session?.set({ 'fn:hiddenWin': w.id }).catch(() => {});
    return w.tabs[0];
  }
  return chrome.tabs.create({ url, active: false });   // fallback: a background tab in the current window
}
async function closeHidden(tabId) {
  await chrome.tabs.remove(tabId).catch(() => {});
}
chrome.windows.onRemoved.addListener(async id => { if (hiddenWin && id === await hiddenWin) hiddenWin = null; });
// When this background script starts fresh, no lookup is running, so a hidden window left over from
// before (e.g. Chrome stopped the script mid-lookup) can go.
chrome.storage.session?.get('fn:hiddenWin').then(({ 'fn:hiddenWin': old } = {}) => {
  if (old && !hiddenWin) chrome.windows.remove(old).catch(() => {});
}).catch(() => {});

// Fragrantica's own search page, read in a background tab (used when Bing finds nothing or is blocked).
async function fragranticaSearch(query) {
  const tab = await openHidden('https://www.fragrantica.com/search/?query=' + encodeURIComponent(query));
  try {
    await waitForLoad(tab.id).catch(() => {});
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      // The page also lists trending perfumes; only keep result links that mention a word of the search,
      // and wait for the results to arrive (they load after the page).
      func: async words => {
        const sleep = ms => new Promise(r => setTimeout(r, ms));
        const norm = x => decodeURIComponent(x).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        const read = () => [...new Set([...document.querySelectorAll('a[href*="/perfume/"]')].map(a => a.href))]
          .filter(u => /-\d+\.html$/.test(u) && words.some(w => norm(u).includes(w)));
        let links = [];
        for (let i = 0; i < 48 && !links.length; i++) {
          links = read();
          if (!links.length) await sleep(250);
        }
        if (links.length) { await sleep(700); links = read(); }   // let the rest of the results arrive
        return links.slice(0, 30);
      },
      args: [tokens(query).filter(w => w.length > 2)]
    });
    return (res?.result || []).filter(u => PERFUME_URL.test(u));
  } catch { return []; } finally {
    closeHidden(tab.id);
  }
}

async function findUrl(query) {
  // While searching, judge strictly (a missing word means: search more). For the final pick, ignore words
  // that none of the found perfumes have (see score).
  const best = (urls, lenient = false) => {
    const vocab = lenient ? new Set(urls.flatMap(u => { const m = u.match(PERFUME_URL); return tokens(decodeURIComponent(m[1] + ' ' + m[2]).replace(/-/g, ' ')); })) : null;
    return urls.map(u => ({ u, s: score(u, query, vocab) })).sort((a, b) => b.s - a.s)[0];
  };
  let found = await bing('site:fragrantica.com/perfume ' + query);
  let top = best(found);
  // Search again if the match is weak, or if we're after a specific version (Parfum, Extrait…)
  // and the best hit isn't that version.
  const qConc = FN.detectConc(query);
  const wrongVersion = top && ['parfum', 'extrait', 'edc', 'edp'].includes(qConc) &&
    FN.detectConc(top.u.match(PERFUME_URL)[2].replace(/-/g, ' ')) !== qConc;
  if (!top || top.s < 0.75 || wrongVersion) {
    found = [...new Set([...found, ...await bing('fragrantica ' + query)])];
    top = best(found);
  }
  // Still nothing good (Bing may also be showing a bot check): ask Fragrantica's own search.
  if (!top || top.s < 0.75) {
    found = [...new Set([...found, ...await fragranticaSearch(FN.stripConc(query) || query)])];
    top = best(found);
  }
  top = best(found, true);
  if (top && top.s > 0.3) return { url: top.u };
  // Nothing good enough: hand back the closest perfumes so the user can pick one.
  const seen = new Set();
  const candidates = found.map(u => ({ u, s: score(u, query) })).filter(x => x.s > 0.15).sort((a, b) => b.s - a.s)
    .filter(x => { const id = (x.u.match(/-(\d+)\.html/) || [])[1]; if (!id || seen.has(id)) return false; seen.add(id); return true; })
    .slice(0, 3).map(({ u }) => {
      const m = u.match(PERFUME_URL), id = u.match(/-(\d+)\.html/)[1];
      const words = x => decodeURIComponent(x).replace(/-/g, ' ');
      return { url: u, brand: words(m[1]), name: words(m[2]), img: `https://fimgs.net/mdimg/perfume-thumbs/375x500.${id}.jpg` };
    });
  return { url: null, candidates };
}

// Turn an English fragrantica.com perfume URL into the same perfume on another language site.
function toLang(url, lang) {
  const L = FN.LANGS[lang];
  const m = url.match(PERFUME_URL);
  if (!L || lang === 'en' || !m) return url;
  const id = (url.match(/-(\d+)\.html/) || [])[1];
  return `https://${L.host}/${L.path}/${m[1]}/${m[2]}-${id}.html`;
}
const isFragranticaUrl = u => { try { return FN.LANG_HOSTS.includes(new URL(u).host); } catch { return false; } };

// ---------- read the Fragrantica page in a background tab ----------
function waitForLoad(tabId, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error('timeout')); }, timeout);
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') { cleanup(); resolve(); }
    };
    const cleanup = () => { clearTimeout(timer); chrome.tabs.onUpdated.removeListener(listener); };
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then(t => {
      if (t.status === 'complete' && t.url && !t.url.startsWith('about:')) { cleanup(); resolve(); }
    }).catch(() => {});
  });
}

// Runs inside the Fragrantica page (MAIN world). Must be self-contained.
async function scrapeInPage(dupeHouses = []) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const txt = e => (e?.textContent || '').replace(/\s+/g, ' ').trim();
  const withTimeout = (p, ms) => Promise.race([p, sleep(ms).then(() => null)]);
  const tryGet = fn => { try { return fn(); } catch { return undefined; } };

  // Wait for Fragrantica's decoder (also covers a Cloudflare check finishing).
  for (let i = 0; i < 40 && typeof window._pd !== 'function'; i++) await sleep(250);
  if (typeof window._pd !== 'function') return { error: 'blocked' };

  // `status` and `similar_perfumes` are encoded globals declared by the page's own scripts.
  let rawStatus = null, rawSimilar = null, decStatus = null, similar = null;
  try { rawStatus = status; } catch {}
  try { rawSimilar = similar_perfumes; } catch {}
  if (rawStatus && typeof rawStatus === 'object') {
    try { decStatus = await withTimeout(window._pd(rawStatus), 6000); } catch {}
  }
  if (rawSimilar && typeof rawSimilar === 'object') {
    try { similar = await withTimeout(window._pd(rawSimilar), 6000); } catch {}
  }
  // Pros & cons that Fragrantica summarises from reviews (`ai_opinions`, also encoded), with agree/disagree votes.
  let opinions = null;
  try {
    const rawOp = ai_opinions;
    if (rawOp && typeof rawOp === 'object') opinions = await withTimeout(window._pd(rawOp), 6000);
  } catch {}
  const opinionList = list => (Array.isArray(list) ? list : Object.values(list || {}))
    .map(o => ({ text: String(o.opinion || '').trim(), yes: +o.vote_yes || 0, no: +o.vote_no || 0, score: +o.score || 0 }))
    .filter(o => o.text).sort((a, b) => b.score - a.score).slice(0, 3);
  const pc = opinions ? { pros: opinionList(opinions.pros), cons: opinionList(opinions.cons) } : null;
  let pcLabels = {};
  try { pcLabels = prosConsLangVar || {}; } catch {}

  const st = decStatus?.status || {};
  const orig = similar?.original_perfume;

  // Name and audience ("for men", "voor heren", …) — language-neutral where possible.
  const h1 = txt(document.querySelector('h1'));
  const baseTitle = orig ? `${orig.naslov} ${orig.dizajner}` : '';
  const title = baseTitle || h1.replace(/\s+for (wo)?men( and (wo)?men)?$/i, '');
  const audience = baseTitle && h1.startsWith(baseTitle) ? h1.slice(baseTitle.length).trim() : '';

  // Main accords: coloured bars (a div with width + background, holding a span.truncate).
  const readAccords = doc => {
    const bars = [...doc.querySelectorAll('div[style*="width"]')]
      .filter(d => d.querySelector('span.truncate') && /background/i.test(d.getAttribute('style') || ''));
    if (!bars.length) return { list: [], heading: '' };
    const box = bars[0].parentElement?.parentElement; // the column holding all bars
    const group = box ? bars.filter(b => box.contains(b)) : bars;
    const heading = txt(box?.parentElement?.querySelector('h6'));
    return {
      heading,
      list: group.map(d => ({
        name: txt(d),
        width: parseFloat(d.style.width) || 0,
        bg: d.style.backgroundColor || d.style.background || '',
        fg: d.style.color || ''
      })).filter(a => a.name).slice(0, 8)
    };
  };

  // Notes: every link with a picture inside a pyramid level. Label = that level's heading.
  const namesIn = root => {
    const names = [];
    root.querySelectorAll('a').forEach(a => {
      const img = a.querySelector('img');
      if (!img || !/-\d+\.html/.test(a.getAttribute('href') || '')) return;
      const n = txt(a) || img.getAttribute('alt')?.trim() || '';
      if (n && !names.some(x => x.name === n)) names.push({ name: n, img: img.getAttribute('src') || '', url: a.href });
    });
    return names;
  };
  const labelFor = c => {
    let p = c;
    for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
      for (let s = p.previousElementSibling; s; s = s.previousElementSibling) {
        const h = s.matches('h4') ? s : s.querySelector('h4');
        if (h && txt(h)) return txt(h);
      }
    }
    return '';
  };
  const readNotes = doc => {
    const notes = [];
    doc.querySelectorAll('.pyramid-level-container').forEach(c => {
      const names = namesIn(c);
      if (names.length) notes.push({ label: labelFor(c), names });
    });
    if (!notes.length) {
      const pyr = doc.querySelector('#pyramid');
      const flat = pyr ? namesIn(pyr) : [];
      if (flat.length) notes.push({ label: '', names: flat });
    }
    return notes;
  };

  // In a background tab Fragrantica re-renders the pyramid after "load", so wait for it…
  let acc = readAccords(document);
  let notes = readNotes(document);
  for (let i = 0; i < 16 && (!notes.length || !acc.list.length); i++) {
    await sleep(250);
    if (!notes.length) notes = readNotes(document);
    if (!acc.list.length) acc = readAccords(document);
  }
  // …and if it's still empty, read the page's original server HTML instead.
  if (!notes.length || !acc.list.length) {
    try {
      const html = await withTimeout(fetch(location.href, { credentials: 'include' }).then(r => r.text()), 8000);
      if (html) {
        const raw = new DOMParser().parseFromString(html, 'text/html');
        if (!notes.length) notes = readNotes(raw);
        if (!acc.list.length) acc = readAccords(raw);
      }
    } catch {}
  }

  // Fragrantica's own translated labels for this language.
  const lsl = tryGet(() => LongevitySillageLangLanguage) || {};
  const lch = tryGet(() => longevityChartLang) || {};
  const sch = tryGet(() => sillageChartLang) || {};
  const gl = tryGet(() => genderLangVar) || {};
  const pv = tryGet(() => priceValueLangVar) || {};
  const se = tryGet(() => seasonsLangVar) || {};
  const sm = tryGet(() => similarLangVar) || {};
  const plain = v => (typeof v === 'string' ? v.replace(/<em>.*$/i, '').trim() : '');
  const pick = (obj, keys, fallback) => keys.map((k, i) => plain(obj[k]) || fallback[i]);

  const votes = (obj, labels) => {
    if (!obj) return null;
    const rows = labels.map((label, i) => ({ label, n: +obj[i + 1] || 0 }));
    const total = rows.reduce((s, r) => s + r.n, 0);
    if (!total) return null;
    return { rows, total, top: rows.reduce((a, b) => (b.n > a.n ? b : a)).label };
  };

  const longLabels = pick(lch, [1, 2, 3, 4, 5], ['very weak', 'weak', 'moderate', 'long lasting', 'eternal']);
  const silLabels = pick(sch, [1, 2, 3, 4], ['intimate', 'moderate', 'strong', 'enormous']);
  const pvLabels = pick(pv, [1, 2, 3, 4, 5], ['way overpriced', 'overpriced', 'ok', 'good value', 'great value']);
  const gKeys = ['female', 'female_unisex', 'unisex', 'male_unisex', 'male'];
  const gLabels = pick(gl, gKeys, ['female', 'more female', 'unisex', 'more male', 'male']);
  const wearKeys = ['winter', 'spring', 'summer', 'autumn', 'day', 'night'];

  const simList = similar?.similar_perfumes
    ? (Array.isArray(similar.similar_perfumes) ? similar.similar_perfumes : Object.values(similar.similar_perfumes))
    : [];
  // Houses known for affordable alternatives ("dupes") of designer and niche perfumes.
  const norm = x => (x || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  const isDupeHouse = brand => dupeHouses.some(h => norm(brand) === h || norm(brand).startsWith(h + ' '));
  const origIsDupe = orig && isDupeHouse(orig.dizajner);

  const simAll = simList
    .filter(s => s.perfume)
    .sort((a, b) => (b.votes || 0) - (a.votes || 0))
    .map(s => ({
      name: s.perfume.naslov,
      brand: s.perfume.dizajner,
      url: new URL(s.perfume.perfume_url, location.origin).href,
      img: s.perfume.thumbnail || '',
      votes: s.votes || 0,
      dupe: !origIsDupe && isDupeHouse(s.perfume.dizajner)
    }));
  const sim = simAll.slice(0, 6);
  const dupes = simAll.filter(s => s.dupe).slice(0, 4);

  // Main bottle photo (falls back to Fragrantica's standard thumbnail URL for this perfume id).
  const pid = (location.pathname.match(/-(\d+)\.html$/) || [])[1];
  const photo = document.querySelector('img[itemprop="image"]')?.getAttribute('src') ||
    (pid ? `https://fimgs.net/mdimg/perfume-thumbs/375x500.${pid}.jpg` : '');

  return {
    title,
    photo,
    url: location.href.split('#')[0],
    lang: document.documentElement.lang || '',
    rating: st.rating_average ? (+st.rating_average).toFixed(2) : txt(document.querySelector('[itemprop="ratingValue"]')),
    ratingCount: st.rating_sum ? String(st.rating_sum) : txt(document.querySelector('[itemprop="ratingCount"]')),
    accords: acc.list,
    notes,
    longevity: votes(st.longevity, longLabels),
    sillage: votes(st.sillage, silLabels),
    priceValue: votes(st.price_value, pvLabels),
    gender: st.gender ? (() => {
      const rows = gKeys.map((k, i) => ({ label: gLabels[i], n: +st.gender[k] || 0 }));
      const total = rows.reduce((a, r) => a + r.n, 0);
      return total ? { rows, total, top: rows.reduce((a, b) => (b.n > a.n ? b : a)).label } : null;
    })() : null,
    wear: wearKeys.map(k => ({ label: plain(se[k]) || k, n: +st[k] || 0 })),
    // Last 4-digit year in the title ("… for men 2010", "… 2010年 男用 香水", "… 2010 לגברים").
    year: ((document.title.match(/(?:19|20)\d{2}(?!\d)/g) || []).pop() || ''),
    audience,
    // Section titles in the page's language (empty = use the extension's own text).
    labels: {
      accords: acc.heading,
      longevity: plain(lsl.lp_longevity),
      sillage: plain(lsl.lp_projection),
      gender: plain(gl.gender),
      wear: plain(se.title),
      similar: plain(sm.reminds_of),
      prosCons: plain(pcLabels.what_people_say),
      pros: plain(pcLabels.pros),
      cons: plain(pcLabels.cons)
    },
    similar: sim,
    prosCons: pc && (pc.pros.length || pc.cons.length) ? pc : null,
    dupes
  };
}

async function readFragrantica(url) {
  const tab = await openHidden(url);
  try {
    await waitForLoad(tab.id);
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      func: scrapeInPage,
      args: [DUPE_HOUSES]
    });
    return res?.result;
  } finally {
    closeHidden(tab.id);
  }
}

// ---------- pros & cons from the English site ----------
// Fragrantica only has pros & cons on fragrantica.com, so for other languages they're read from there
// (in English) after the panel is shown.
function opinionsInPage() {
  return (async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    for (let i = 0; i < 40 && typeof window._pd !== 'function'; i++) await sleep(250);
    let raw = null;
    try { raw = ai_opinions; } catch {}
    if (!raw || typeof window._pd !== 'function') return null;
    const d = await Promise.race([window._pd(raw), sleep(6000).then(() => null)]);
    const list = l => (Array.isArray(l) ? l : Object.values(l || {}))
      .map(o => ({ text: String(o.opinion || '').trim(), yes: +o.vote_yes || 0, no: +o.vote_no || 0, score: +o.score || 0 }))
      .filter(o => o.text).sort((a, b) => b.score - a.score).slice(0, 3);
    return d && !Array.isArray(d) ? { pros: list(d.pros), cons: list(d.cons) } : { pros: [], cons: [] };
  })();
}
async function englishOpinions(url) {
  const m = String(url).match(/\/([^/]+)\/([^/]+-(\d+)\.html)$/);
  if (!m) return null;
  const key = 'pc1:' + m[3];
  const c = (await chrome.storage.local.get(key))[key];
  if (c && Date.now() - c.t < 14 * 864e5) return c.data;
  const tab = await openHidden(`https://www.fragrantica.com/perfume/${m[1]}/${m[2]}`);
  try {
    await waitForLoad(tab.id).catch(() => {});
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', func: opinionsInPage });
    const data = res?.result;
    if (data) await chrome.storage.local.set({ [key]: { t: Date.now(), data } });
    return data;
  } catch { return null; } finally {
    closeHidden(tab.id);
  }
}

// ---------- images ----------
// Shop pages may block outside images, so embed note and bottle pictures as data URLs.
async function toDataUrl(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return '';
    const type = r.headers.get('content-type') || 'image/jpeg';
    const bytes = new Uint8Array(await r.arrayBuffer());
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return `data:${type};base64,${btoa(bin)}`;
  } catch { return ''; }
}

async function inlineImages(data) {
  // A perfume can be in both "similar" and "dupes" (same object), so de-duplicate first.
  const items = [...new Set([...data.notes.flatMap(t => t.names), ...data.similar, ...(data.dupes || [])])].filter(x => x.img && /^https:\/\//.test(x.img));
  const urls = [...new Set([...items.map(x => x.img), data.photo].filter(u => u && /^https:\/\//.test(u)))].slice(0, 41);
  const map = Object.fromEntries(await Promise.all(urls.map(async u => [u, await toDataUrl(u)])));
  items.forEach(x => { x.img = map[x.img] || ''; });
  if (data.photo) data.photo = map[data.photo] || '';
  return data;
}

// ---------- shared prices (opt-in) ----------
// Only while "Share prices anonymously" is on. What is sent: the Fragrantica perfume number, size,
// price, currency and the shop's domain (built-in shops only), plus a random install id that is
// deleted when sharing is turned off. No page URLs, no account, nothing else.
const PID_RE = /^[1-9]\d{0,8}$/;
const sharing = async () => !!(await chrome.storage.sync.get('settings')).settings?.sharePrices;
async function installId() {
  let { 'fn:installId': id } = await chrome.storage.local.get('fn:installId');
  if (!id) { id = crypto.randomUUID(); await chrome.storage.local.set({ 'fn:installId': id }); }
  return id;
}
const communityCache = new Map();   // "perfumeId|currency" → { t, data }
async function communityPrices(perfumeId, currency) {
  if (!PID_RE.test(perfumeId || '') || !await sharing()) return null;
  const key = perfumeId + '|' + (currency || '');
  const c = communityCache.get(key);
  if (c && Date.now() - c.t < 10 * 60e3) return c.data;
  try {
    const q = /^[A-Z]{3}$/.test(currency || '') ? '?currency=' + currency : '';
    const r = await fetch(`${FN.API_BASE}/prices/${perfumeId}${q}`, { credentials: 'omit', signal: AbortSignal.timeout(8000) });
    if (!r.ok) return null;
    const data = await r.json();
    communityCache.set(key, { t: Date.now(), data });
    if (communityCache.size > 200) communityCache.delete(communityCache.keys().next().value);
    return data;
  } catch { return null; }
}
async function sharePrices(perfumeId, prices, pageUrl) {
  if (!PID_RE.test(perfumeId || '') || !Array.isArray(prices) || !await sharing()) return;
  let host;
  try { host = new URL(pageUrl).hostname; } catch { return; }
  const shop = FN.builtInShop(host);
  if (!shop) return;   // shops the user added themselves are never shared
  const id = await installId();
  const { 'fn:shared': sent = {} } = await chrome.storage.session.get('fn:shared').catch(() => ({}));
  const day = Date.now() - 864e5;
  for (const k of Object.keys(sent)) if (sent[k] < day) delete sent[k];
  for (const p of prices.slice(0, 8)) {
    if (!p.currency || !(p.ml > 0) || !(p.price > 0)) continue;   // without a currency sign we can't be sure
    const body = { perfumeId, ml: p.ml, price: p.price, currency: p.currency, shop };
    const k = Object.values(body).join('|');
    if (sent[k]) continue;   // already sent in the last day
    try {
      const r = await fetch(`${FN.API_BASE}/prices`, {
        method: 'POST', credentials: 'omit', signal: AbortSignal.timeout(8000),
        headers: { 'Content-Type': 'application/json', 'X-Install-Id': id }, body: JSON.stringify(body)
      });
      if (r.status === 429 || r.status >= 500) break;
      sent[k] = Date.now();   // rejected prices (422) aren't retried either
    } catch { break; }
  }
  await chrome.storage.session.set({ 'fn:shared': sent }).catch(() => {});
}
// "Help build the open perfume database" (off by default): facts a built-in shop shows about a perfume
// (name, brand, concentration, sizes, barcode, the notes and family it lists). Nothing about the user;
// the random install id only lets the server limit how much one install sends.
const strList = (a, max, len) => (Array.isArray(a) ? a : []).map(x => String(x).trim().slice(0, len)).filter(Boolean).slice(0, max);
async function shareFacts(perfumeId, f, pageUrl) {
  if (!f || typeof f !== 'object' || !(await chrome.storage.sync.get('settings')).settings?.shareFacts) return;
  let host;
  try { host = new URL(pageUrl).hostname; } catch { return; }
  const shop = FN.builtInShop(host);
  if (!shop) return;   // shops the user added themselves are never shared
  const body = {
    shop,
    perfumeId: PID_RE.test(perfumeId || '') ? perfumeId : null,
    brand: String(f.brand || '').slice(0, 80),
    name: String(f.name || '').slice(0, 120),
    conc: ['extrait', 'parfum', 'edp', 'edt', 'edc'].includes(f.conc) ? f.conc : null,
    gender: ['m', 'f', 'u'].includes(f.gender) ? f.gender : null,
    sizes: (Array.isArray(f.sizes) ? f.sizes : []).map(Number).filter(x => x > 0 && x <= 1000).slice(0, 8),
    gtins: strList(f.gtins, 8, 14).filter(g => /^\d{8,14}$/.test(g)),
    notes: { top: strList(f.notes?.top, 15, 40), heart: strList(f.notes?.heart, 15, 40), base: strList(f.notes?.base, 15, 40),
      mentioned: FN.officialSite(host) ? strList(f.notes?.mentioned, 20, 40) : [] },
    families: strList(f.families, 6, 40),
    lang: /^[a-z]{2}(-[a-z]{2})?$/.test(f.lang || '') ? f.lang : null
  };
  if (!body.name || !body.brand) return;
  // Once per perfume page and shop a day, unless the page now says more (a new extension version reads more notes,
  // or the page finished loading its notes): then the fuller facts replace the earlier ones on the server.
  const said = ['top', 'heart', 'base', 'mentioned'].map(t => body.notes[t].length).join('.') + '.' + body.gtins.length;
  const k = shop + '|' + body.brand + '|' + body.name + '|' + body.conc + '|' + said;
  const { 'fn:factsSent': sent = {} } = await chrome.storage.session.get('fn:factsSent').catch(() => ({}));
  for (const x of Object.keys(sent)) if (sent[x] < Date.now() - 864e5) delete sent[x];
  if (sent[k]) return;
  try {
    const r = await fetch(`${FN.API_BASE}/facts`, {
      method: 'POST', credentials: 'omit', signal: AbortSignal.timeout(8000),
      headers: { 'Content-Type': 'application/json', 'X-Install-Id': await installId() }, body: JSON.stringify(body)
    });
    if (r.status < 500 && r.status !== 429) sent[k] = Date.now();
  } catch {}
  await chrome.storage.session.set({ 'fn:factsSent': sent }).catch(() => {});
}

// Turning sharing off forgets the install id, so turning it on again starts as a new, unlinked install.
chrome.storage.onChanged.addListener((changes, area) => {
  const was = changes.settings?.oldValue, now = changes.settings?.newValue;
  if (area === 'sync' && (was?.sharePrices || was?.shareFacts) && !now?.sharePrices && !now?.shareFacts) {
    chrome.storage.local.remove(['fn:installId', 'fn:suggested']).catch(() => {});
    chrome.storage.session.remove(['fn:shared', 'fn:mine']).catch(() => {});
    communityCache.clear();
  }
});

// "Own database first": what the Fragrance Notes database knows about the perfume on this shop page.
// For everyone, not only users who share: it's an anonymous question (brand, name, concentration, gender, barcodes;
// no install id), the server stores nothing and doesn't log it. Remembered for an hour per perfume.
const ownCache = new Map();
async function ownLookup(f) {
  if (!f || typeof f !== 'object') return null;
  const q = new URLSearchParams();
  const gtins = strList(f.gtins, 8, 14).filter(g => /^\d{8,14}$/.test(g));
  if (gtins.length) q.set('gtin', gtins.join(','));
  if (f.brand) q.set('brand', String(f.brand).slice(0, 80));
  if (f.name) q.set('name', String(f.name).slice(0, 120));
  if (['extrait', 'parfum', 'edp', 'edt', 'edc'].includes(f.conc)) q.set('conc', f.conc);
  if (['m', 'f'].includes(f.gender)) q.set('gender', f.gender);
  if (!gtins.length && !(f.brand && f.name)) return null;
  const key = q.toString();
  const c = ownCache.get(key);
  if (c && Date.now() - c.t < 3600e3) return c.data;
  try {
    const r = await fetch(`${FN.API_BASE}/catalog/lookup?${key}`, { credentials: 'omit', signal: AbortSignal.timeout(6000) });
    if (!r.ok) return null;
    const data = (await r.json())?.perfume || null;
    ownCache.set(key, { t: Date.now(), data });
    if (ownCache.size > 200) ownCache.delete(ownCache.keys().next().value);
    return data;
  } catch { return null; }
}


// The note pop-up: the Fragrance Notes description of a note (how it smells, where it comes from) and its page on
// fragrancenotes.app. Anonymous like the lookup above: only the note's name and the language, no install id.
// Kept 3 days in this browser (texts are rewritten at night); null when the site has no page for the note.
async function ownNote(key, lang) {
  key = String(key || '').slice(0, 60);
  lang = /^[a-z]{2}$/.test(lang || '') ? lang : 'en';
  if (!key) return null;
  const ck = `n3:${lang}:${key}`;
  const c = (await chrome.storage.local.get(ck))[ck];
  if (c && Date.now() - c.t < 3 * 864e5) return c.data;
  try {
    const r = await fetch(`${FN.API_BASE}/catalog/note?key=${encodeURIComponent(key)}&lang=${lang}`, { credentials: 'omit', signal: AbortSignal.timeout(6000) });
    if (!r.ok) return null;
    const data = (await r.json())?.note || null;
    if (data && !/^https:\/\/fragrancenotes\.app\//.test(data.url || '')) return null;
    await chrome.storage.local.set({ [ck]: { t: Date.now(), data } });
    return data;
  } catch { return null; }
}

// "You helped confirm …" in the toolbar menu: what this install's shared facts did for the database. Only for
// installs that share (they have an install id; none is made here), read-only on the server. Kept 10 minutes.
async function myContribution() {
  const { 'fn:installId': id } = await chrome.storage.local.get('fn:installId');
  if (!id) return null;
  const { 'fn:mine': c } = await chrome.storage.session.get('fn:mine').catch(() => ({}));
  if (c && Date.now() - c.t < 600e3) return c.data;
  try {
    const r = await fetch(`${FN.API_BASE}/facts/mine`, {
      credentials: 'omit', headers: { 'X-Install-Id': id }, signal: AbortSignal.timeout(6000)
    });
    if (!r.ok) return null;
    const data = await r.json();
    await chrome.storage.session.set({ 'fn:mine': { t: Date.now(), data } }).catch(() => {});
    return data;
  } catch { return null; }
}

// ---------- messaging ----------
chrome.runtime.onMessage.addListener((msg, sender, send) => {
  (async () => {
    if (msg.type === 'open-options') { chrome.runtime.openOptionsPage(); return send({ ok: true }); }
    if (msg.type === 'open-favs') { chrome.tabs.create({ url: chrome.runtime.getURL('favourites.html') }); return send({ ok: true }); }
    if (msg.type === 'community') return send(await communityPrices(msg.perfumeId, msg.currency));
    if (msg.type === 'share') { sharePrices(msg.perfumeId, msg.prices, sender.url); return send({ ok: true }); }
    if (msg.type === 'facts') { shareFacts(msg.perfumeId, msg.facts, sender.url); return send({ ok: true }); }
    if (msg.type === 'own') return send(await ownLookup(msg.facts));
    if (msg.type === 'mine') return send(await myContribution());
    if (msg.type === 'note') return send(await noteInfo(msg.url));
    if (msg.type === 'ownNote') return send(await ownNote(msg.key, msg.lang));
    if (msg.type === 'opinions') return send(await englishOpinions(msg.url));
    if (msg.type !== 'lookup') return;
    const query = msg.query.trim();
    const lang = FN.LANGS[msg.lang] ? msg.lang : 'en';
    const key = keyFor(query, lang);
    if (!msg.force) {
      const c = (await chrome.storage.local.get(key))[key];
      if (c && Date.now() - c.t < TTL) return send({ data: c.data, cached: true });
    }
    let url = null;
    try {
      let candidates = [];
      if (isFragranticaUrl(query)) url = query;
      else ({ url, candidates = [] } = await findUrl(query));
      if (url && !isFragranticaUrl(query)) url = toLang(url, lang);
      if (!url) {
        for (const c of candidates) { c.url = toLang(c.url, lang); c.img = await toDataUrl(c.img) || ''; }
        return send({ error: 'notfound', candidates });
      }
      const data = await readFragrantica(url);
      if (!data || data.error) return send({ error: data?.error || 'empty', url });
      if (!data.notes.length && !data.accords.length && !data.longevity) return send({ error: 'empty', url });
      await inlineImages(data);
      // Only cache complete results, so a hiccup doesn't stick for 14 days.
      if (data.notes.length) {
        const entry = { t: Date.now(), data };
        // A perfume picked from "Did you mean" is also remembered under the original search.
        const alias = typeof msg.alias === 'string' && msg.alias.trim() ? keyFor(msg.alias, lang) : null;
        await chrome.storage.local.set(alias ? { [key]: entry, [alias]: entry } : { [key]: entry });
      }
      send({ data });
    } catch (e) {
      send({ error: e.message, url });
    }
  })();
  return true; // async reply
});

// The toolbar button opens popup.html (enable/disable, add this site, settings).

// ---------- shops you add yourself ----------
// Each added shop needs the user's permission for that site; we then register the content
// scripts for it so the 🌸 appears there just like on the built-in shops.
async function syncCustomShops() {
  try {
    const { customShops = [] } = await chrome.storage.sync.get('customShops');
    try { await chrome.scripting.unregisterContentScripts({ ids: ['fn-custom'] }); } catch {}
    try { await chrome.scripting.unregisterContentScripts({ ids: ['fn-all'] }); } catch {}
    // Optional: run on every website (the content script only shows the 🌸 on perfume product pages).
    const { settings } = await chrome.storage.sync.get('settings');
    const ALL = ['https://*/*', 'http://*/*'];
    if (settings?.allSites && await chrome.permissions.contains({ origins: ALL })) {
      await chrome.scripting.registerContentScripts([{
        id: 'fn-all', matches: ALL, js: ['settings.js', 'i18n-panel.js', 'panel-ui.js', 'content.js'], runAt: 'document_idle'
      }]);
    }
    const granted = [];
    for (const d of customShops) {
      for (const pattern of FN.shopPatterns(d)) {
        if (await chrome.permissions.contains({ origins: [pattern] })) granted.push(pattern);
      }
    }
    if (granted.length) {
      await chrome.scripting.registerContentScripts([{
        id: 'fn-custom', matches: granted, js: ['settings.js', 'i18n-panel.js', 'panel-ui.js', 'content.js'], runAt: 'document_idle'
      }]);
    }
  } catch (e) { console.warn('Fragrance Notes: could not register custom shops', e); }
}
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'sync') return;
  if (changes.customShops || (changes.settings && changes.settings.oldValue?.allSites !== changes.settings.newValue?.allSites)) syncCustomShops();
});
chrome.permissions.onAdded.addListener(async () => {
  // Finish an "Add this site" started from the toolbar menu.
  const { 'fn:pendingShop': pending } = await chrome.storage.local.get('fn:pendingShop');
  if (pending?.domain && await chrome.permissions.contains({ origins: FN.shopPatterns(pending.domain) })) {
    await chrome.storage.local.remove('fn:pendingShop');
    const { customShops = [] } = await chrome.storage.sync.get('customShops');
    if (!customShops.includes(pending.domain)) await chrome.storage.sync.set({ customShops: [...customShops, pending.domain] });
    try {
      await chrome.scripting.executeScript({ target: { tabId: pending.tabId }, files: ['settings.js', 'i18n-panel.js', 'panel-ui.js', 'content.js'] });
    } catch {}
  }
  syncCustomShops();
});
chrome.permissions.onRemoved.addListener(syncCustomShops);
chrome.runtime.onStartup.addListener(syncCustomShops);
chrome.runtime.onInstalled.addListener(syncCustomShops);

// Show the welcome page once, on a fresh install (not on updates or browser updates).
chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === 'install') chrome.tabs.create({ url: chrome.runtime.getURL('welcome.html') }).catch(() => {});
});

// Show "OFF" on the toolbar icon while the extension is disabled.
async function updateBadge() {
  try {
    const { settings } = await chrome.storage.sync.get('settings');
    const off = settings && settings.enabled === false;
    await chrome.action.setBadgeText({ text: off ? 'OFF' : '' });
    await chrome.action.setBadgeBackgroundColor({ color: '#6b6b6b' });
  } catch {}
}
chrome.storage.onChanged.addListener((changes, area) => { if (area === 'sync' && changes.settings) updateBadge(); });
chrome.runtime.onStartup.addListener(updateBadge);
chrome.runtime.onInstalled.addListener(updateBadge);

// ---------- price alerts for favourites ----------
// Set on the favourites page ("alert:<Fragrantica id>" in storage.sync: size in ml, price, currency). Every six
// hours the prices other users shared (the same request as the panel's comparison, so only while sharing is on)
// are checked; when a shop's lowest price for that size is at or below the alert price, one notification is shown.
// The same or a higher price isn't announced again within a week. Notifications need the optional "notifications"
// permission, which the favourites page asks for when the first alert is set.
const ALERT_EVERY_MIN = 360;
function scheduleAlerts() {
  chrome.alarms?.get('priceAlerts').then(a => { if (!a) chrome.alarms.create('priceAlerts', { periodInMinutes: ALERT_EVERY_MIN, delayInMinutes: 10 }); }).catch(() => {});
}
chrome.runtime.onStartup.addListener(scheduleAlerts);
chrome.runtime.onInstalled.addListener(scheduleAlerts);
chrome.alarms?.onAlarm.addListener(a => { if (a.name === 'priceAlerts') checkAlerts().catch(() => {}); });

let alertClicksOn = false;
function listenAlertClicks() {
  if (alertClicksOn || !chrome.notifications) return;
  alertClicksOn = true;
  chrome.notifications.onClicked.addListener(id => {
    if (!id.startsWith('alert:')) return;
    chrome.tabs.create({ url: chrome.runtime.getURL('favourites.html#' + id.slice(6)) }).catch(() => {});
    chrome.notifications.clear(id);
  });
}
listenAlertClicks();

async function checkAlerts() {
  if (!chrome.notifications || !await sharing()) return;
  listenAlertClicks();
  const all = await chrome.storage.sync.get(null);
  const list = Object.entries(all).filter(([k, v]) => k.startsWith('alert:') && v && v.price > 0 && v.ml > 0);
  if (!list.length) return;
  const S = await FN.loadSettings();
  const { 'fn:alerted': told = {} } = await chrome.storage.local.get('fn:alerted');
  for (const [k, a] of list) {
    const id = k.slice(6);
    const data = await communityPrices(id, a.cur);
    const size = (data?.sizes || []).find(s => Math.abs(s.ml - a.ml) < 0.5);
    const best = Object.entries(size?.lows || {}).sort((x, y) => x[1] - y[1])[0];
    if (!best || best[1] > a.price) continue;
    const prev = told[id];
    if (prev && prev.price <= best[1] && Date.now() - prev.t < 7 * 864e5) continue;
    const cur = data.currency || a.cur || 'EUR';
    let price;
    try { price = new Intl.NumberFormat(S.lang, { style: 'currency', currency: cur }).format(best[1]); } catch { price = `${best[1].toFixed(2)} ${cur}`; }
    const name = all['fav:' + id]?.name || 'Fragrance Notes';
    await chrome.notifications.create('alert:' + id, {
      type: 'basic', iconUrl: chrome.runtime.getURL('icons/128.png'),
      title: FN_st(S.lang, 'al_notifT', { name }),
      message: FN_st(S.lang, 'al_notifD', { ml: Math.round(a.ml), price, shop: best[0] })
    }).catch(() => {});
    told[id] = { price: best[1], t: Date.now() };
  }
  await chrome.storage.local.set({ 'fn:alerted': told });
}

// ---------- shops people add themselves (opt-in) ----------
// While sharing is on, the domains of shops the user added in Settings (only the domain, e.g. "armani.com") are
// sent once, so popular ones can be reviewed and added to the built-in list. Built-in shops are skipped here and on
// the server. "fn:suggested" remembers what was sent; it's cleared with the install id when sharing is turned off.
async function suggestCustomShops() {
  try {
    if (!await sharing()) return;
    const { customShops = [] } = await chrome.storage.sync.get('customShops');
    const { 'fn:suggested': sent = [] } = await chrome.storage.local.get('fn:suggested');
    const todo = [...new Set(customShops.map(d => String(d).toLowerCase().replace(/^www\./, '')))]
      .filter(d => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(d) && d.length <= 100 && !FN.builtInShop(d) && !sent.includes(d)).slice(0, 20);
    if (!todo.length) return;
    const r = await fetch(`${FN.API_BASE}/shops/suggest`, {
      method: 'POST', credentials: 'omit', signal: AbortSignal.timeout(8000),
      headers: { 'Content-Type': 'application/json', 'X-Install-Id': await installId() },
      body: JSON.stringify({ domains: todo })
    });
    if (r.ok) await chrome.storage.local.set({ 'fn:suggested': [...sent, ...todo].slice(-200) });
  } catch {}
}
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'sync' && (changes.customShops || changes.settings)) suggestCustomShops();
});
chrome.runtime.onStartup.addListener(suggestCustomShops);
