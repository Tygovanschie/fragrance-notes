// Toolbar menu: the perfume on this page, a quick search, on/off and this site's status.
(async () => {
  let S = await FN.loadSettings();
  const $ = id => document.getElementById(id);
  const st = (k, v) => FN_st(S.lang, k, v);
  document.documentElement.lang = S.lang;
  document.documentElement.dir = ['ar', 'he'].includes(S.lang) ? 'rtl' : 'ltr';

  // Same colours as the panel.
  const theme = { onAccent: '#ffffff', ...(FN.THEMES[FN.resolveTheme(S)] || FN.THEMES.plum) };
  for (const [k, v] of Object.entries(theme)) if (k !== 'name' && k !== 'dark') document.documentElement.style.setProperty('--' + k, v);

  const ICON_CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
  const ICON_PLUS = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>';

  // ---------- settings ----------
  $('settings').title = st('p_settings');
  $('settings').addEventListener('click', () => { chrome.runtime.openOptionsPage(); window.close(); });

  // ---------- favourites ----------
  $('favsTitle').textContent = st('p_favs');
  FN.favs.all().then(list => { $('favsSub').textContent = list.length ? st('p_favsN', { n: list.length }) : st('p_favsNone'); });
  $('favs').addEventListener('click', () => { chrome.tabs.create({ url: chrome.runtime.getURL('favourites.html') }); window.close(); });

  // ---------- on / off ----------
  const btn = $('toggle');
  const paint = () => {
    btn.classList.toggle('on', S.enabled);
    document.body.classList.toggle('off', !S.enabled);
    $('toggleTitle').textContent = st(S.enabled ? 'p_enabled' : 'p_disabled');
    $('toggleSub').textContent = st(S.enabled ? 'p_turnOff' : 'p_turnOn');
    $('state').textContent = st(S.enabled ? 'p_active' : 'p_off');
  };
  paint();
  btn.addEventListener('click', async () => {
    S.enabled = !S.enabled;
    paint();
    await chrome.storage.sync.set({ settings: S });
  });

  // ---------- what sharing did ----------
  // Only while sharing is on; the numbers come from the server for this install (background.js myContribution).
  if (S.sharePrices || S.shareFacts) {
    chrome.runtime.sendMessage({ type: 'mine' }).then(m => {
      if (!m || !m.shared) return;
      const text = m.notesConfirmed ? st('p_mineT', { n: m.notesConfirmed, p: m.perfumes }) : st('p_mineNone', { n: m.shared });
      const p = $('mineText');
      p.textContent = '';
      const b = document.createElement('b');
      b.textContent = m.notesConfirmed ? '✓ ' : '♥ ';
      p.append(b, text + ' ' + st('p_mineLink'));
      $('mine').href = S.lang === 'nl' ? 'https://fragrancenotes.app/nl/database' : 'https://fragrancenotes.app/database';
      $('mine').hidden = false;
    }).catch(() => {});
  }

  // ---------- review request ----------
  // Once, after 10 perfumes looked up (counted in content.js). Clicking either button hides it for good.
  chrome.storage.local.get(['fn:lookups', 'fn:reviewAsked', 'fn:shareReminded', 'fn:shareDeclined']).then(({
    'fn:lookups': n = 0, 'fn:reviewAsked': asked = false, 'fn:shareReminded': reminded = false, 'fn:shareDeclined': declined = false
  }) => {
    // The sharing reminder: also once, after 10 lookups, only while both sharing settings are off and not after a
    // clear "No" on the welcome page or in this card; never together with the review card (that one goes first).
    const reviewFirst = n >= 10 && !asked && !!FN.REVIEW_URL;
    if (n >= 10 && !reviewFirst && !reminded && !declined && !S.sharePrices && !S.shareFacts) {
      const done = no => chrome.storage.local.set(no ? { 'fn:shareReminded': true, 'fn:shareDeclined': true } : { 'fn:shareReminded': true });
      $('shareText').textContent = st('p_shareT');
      $('shareGo').textContent = st('p_shareGo');
      $('shareNo').textContent = st('p_shareNo');
      $('shareClose').title = $('shareClose').ariaLabel = st('p_revClose');
      $('shareGo').addEventListener('click', async () => {
        S = await FN.loadSettings();
        S.sharePrices = true;
        S.shareFacts = true;
        S.shareAsked = true;
        await chrome.storage.sync.set({ settings: S });
        await done(false);
        $('shareText').textContent = st('p_shareThanks');
        $('shareGo').hidden = $('shareNo').hidden = true;
      });
      $('shareNo').addEventListener('click', () => { done(true); $('shareCard').hidden = true; });
      $('shareClose').addEventListener('click', () => { done(false); $('shareCard').hidden = true; });
      $('shareCard').hidden = false;
    }
    if (!reviewFirst) return;
    $('revGo').href = FN.REVIEW_URL;
    const done = () => chrome.storage.local.set({ 'fn:reviewAsked': true });
    $('revText').textContent = st('p_revT');
    $('revGo').textContent = st('p_revGo');
    $('revClose').title = $('revClose').ariaLabel = st('p_revClose');
    $('revGo').addEventListener('click', () => { done(); setTimeout(() => window.close(), 50); });
    $('revClose').addEventListener('click', () => { done(); $('review').hidden = true; });
    $('review').hidden = false;
  }).catch(() => {});

  // ---------- the page ----------
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const ask = msg => chrome.tabs.sendMessage(tab.id, msg).catch(() => null);
  const status = tab?.id ? await ask({ type: 'fn:status' }) : null;   // null = the panel isn't on this page

  if (status?.product) {
    $('now').hidden = false;
    $('nowLabel').textContent = st('p_onPage');
    $('nowName').textContent = status.name;
    $('nowName').title = status.name;
    $('openPanel').textContent = st('p_show');
    $('openPanel').addEventListener('click', async () => { await ask({ type: 'fn:open' }); window.close(); });
  } else if (status) {
    $('nowEmpty').hidden = false;
    $('nowEmpty').textContent = st('p_noPerfume');
  }

  // ---------- look up any perfume ----------
  $('q').placeholder = st('p_searchPh');
  $('go').textContent = st('p_go');
  $('search').addEventListener('submit', async e => {
    e.preventDefault();
    const q = $('q').value.trim();
    if (!q) return;
    // In the panel on this page when it's there; otherwise on Fragrantica.
    const ok = status && S.enabled ? await ask({ type: 'fn:search', query: q }) : null;
    if (!ok) {
      chrome.tabs.create({ url: `https://www.fragrantica.com/search/?query=${encodeURIComponent(q)}` });
    }
    window.close();
  });
  setTimeout(() => { if (!status?.product) $('q').focus(); }, 50);

  // ---------- this site ----------
  let domain = '';
  try { if (/^https?:/.test(tab?.url || '')) domain = FN.cleanDomain(tab.url); } catch {}
  if (!domain) return;

  const builtIn = [...new Set(chrome.runtime.getManifest().content_scripts[0].matches
    .map(m => m.replace(/^https?:\/\/\*\./, '').replace(/\/\*$/, '')))];
  const isBuiltIn = builtIn.some(b => domain === b || domain.endsWith('.' + b));
  let { customShops = [] } = await chrome.storage.sync.get('customShops');
  const isCustom = () => customShops.some(c => domain === c || domain.endsWith('.' + c));
  const allSites = S.allSites && await chrome.permissions.contains({ origins: ['https://*/*', 'http://*/*'] }).catch(() => false);
  const site = $('site');
  site.hidden = false;

  const paintSite = () => {
    if (isBuiltIn || isCustom() || allSites) {
      $('siteIco').innerHTML = ICON_CHECK;
      $('siteTitle').textContent = st('p_works');
      $('siteSub').innerHTML = '';
      $('siteSub').append(st('p_worksD', { domain }));
      if (isCustom()) {
        const rm = document.createElement('button');
        rm.className = 'rm';
        rm.textContent = ' · ' + st('p_remove');
        rm.addEventListener('click', async e => {
          e.stopPropagation();
          const own = customShops.find(c => domain === c || domain.endsWith('.' + c));
          customShops = customShops.filter(c => c !== own);
          await chrome.storage.sync.set({ customShops });
          try { await chrome.permissions.remove({ origins: FN.shopPatterns(own) }); } catch {}
          paintSite();
        });
        $('siteSub').append(rm);
      }
      site.disabled = true;
    } else {
      $('siteIco').innerHTML = ICON_PLUS;
      $('siteTitle').textContent = st('p_add');
      $('siteSub').textContent = st('p_addD', { domain });
      site.disabled = false;
    }
  };
  paintSite();

  site.addEventListener('click', async () => {
    if (site.disabled) return;
    // Chrome may close this menu while its permission prompt is open, so the background
    // script finishes the job (saves the shop and shows the 🌸 on this tab) once allowed.
    chrome.storage.local.set({ 'fn:pendingShop': { domain, tabId: tab.id } });
    const ok = await chrome.permissions.request({ origins: FN.shopPatterns(domain) }).catch(() => false);
    if (!ok) return;
    customShops = [...new Set([...customShops, domain])];
    paintSite();
  });
})();
