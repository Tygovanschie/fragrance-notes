(async () => {
  let S = await FN.loadSettings();
  const $ = id => document.getElementById(id);
  const st = (key, vars) => FN_st(S.lang, key, vars);

  const toast = text => {
    const el = $('saved');
    el.textContent = text || st('saved');
    el.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.remove('show'), 1400);
  };
  const save = async () => { await chrome.storage.sync.set({ settings: S }); toast(); updatePreview(); };

  // ---------- live preview (same code as the in-page panel) ----------
  const previewRoot = $('previewHost').attachShadow({ mode: 'open' });
  previewRoot.innerHTML = `
    <style>${FN_UI.CSS}
      /* Same size as the panel on a shop page: 360px wide by default, as tall as its content up to the screen height. */
      .panel { width:360px; max-width:100%; max-height:min(820px, calc(100vh - 120px)); animation:none; }
      .rz { display:none; }
      .stage { display:flex; flex-direction:column; gap:8px; }
      .stage.r { align-items:flex-end; } .stage.l { align-items:flex-start; }
    </style>
    <style class="theme"></style>
    <div class="stage">
      <button class="pill" title="🌸">${FN_UI.flower(24)}</button>
      <div class="panel">${FN_UI.panelHtml}</div>
    </div>`;
  const pr = s => previewRoot.querySelector(s);
  pr('input').value = 'Creed Aventus';
  pr('form').addEventListener('submit', e => e.preventDefault());

  // If the panel was resized on a shop page, show the preview at that size too.
  chrome.storage.local.get('fn:size').then(r => {
    const z = r['fn:size'];
    if (z?.w) pr('.panel').style.width = Math.min(z.w, 520) + 'px';
    if (z?.h) { pr('.panel').style.height = z.h + 'px'; pr('.panel').style.maxHeight = 'none'; }
  }).catch(() => {});
  chrome.storage.onChanged.addListener((ch, area) => {
    if (area === 'local' && 'fn:size' in ch && !ch['fn:size'].newValue) { pr('.panel').style.width = ''; pr('.panel').style.height = ''; pr('.panel').style.maxHeight = ''; }
  });

  function updatePreview() {
    pr('.theme').textContent = FN_UI.themeCss(FN.resolveTheme(S));
    pr('.panel').classList.toggle('simple', S.style === 'simple');
    pr('.stage').className = 'stage ' + (S.position[1] === 'l' ? 'l' : 'r');
    pr('.body').innerHTML = FN_UI.renderBody(FN_exampleFor(S.lang), S, { allowRemote: true, noRefresh: true, prices: FN_EXAMPLE_PRICES, elsewhere: FN_EXAMPLE_ELSEWHERE, community: S.sharePrices ? FN_EXAMPLE_COMMUNITY : null, pricesOpen: false });
    FN_UI.localizeChrome(previewRoot, S.lang);
    $('cornerName').textContent = st(S.position);
  }

  // ---------- page text in the chosen language ----------
  function translatePage() {
    document.documentElement.lang = S.lang;
    document.title = 'Fragrance Notes – ' + st('p_settings');
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = st(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = st(el.dataset.i18nPh); });
    $('shopsHint').textContent = st('shopsHint', { n: BUILT_IN.length });
    $('shortcut').placeholder = st('shortcutPh');
    buildGroups();
    renderCustomShops();
  }

  // ---------- controls ----------
  for (const [key, t] of Object.entries(FN.THEMES)) {
    const label = document.createElement('label');
    label.className = 'theme';
    label.innerHTML = `
      <input type="radio" name="theme" value="${key}">
      <div class="card" style="background:${t.bg}">
        <div class="top" style="background:${t.head}"></div>
        <div class="mid">
          <i style="width:70%;background:${t.accent}"></i>
          <i style="width:45%;background:${t.soft}"></i>
          <i style="width:55%;background:${t.chip};outline:1px solid ${t.border}"></i>
        </div>
        <div class="name" style="color:${t.fg}">${t.name}</div>
      </div>`;
    $(t.dark ? 'themesDark' : 'themesLight').appendChild(label);
  }

  // "What to show": groups in panel order, translated
  function buildGroups() {
    const sections = $('sections');
    sections.innerHTML = '';
    FN.SECTION_GROUPS.forEach((g, i) => {
      const box = document.createElement('div');
      box.className = 'group';
      box.innerHTML = `<span class="num">${i + 1}</span><div class="gh"><h3>${st('g_' + g.key)}</h3><span class="where">${st('w_' + g.key)}</span></div>
        <div class="items">${g.items.map(([key]) =>
          `<div class="row"><div class="l"><b>${st(key + '_t')}</b><span>${st(key + '_d')}</span></div><label class="sw"><input type="checkbox" data-section="${key}" ${S.sections[key] !== false ? 'checked' : ''}><i></i></label></div>`).join('')}</div>`;
      sections.appendChild(box);
    });
    sections.querySelectorAll('[data-section]').forEach(cb => cb.addEventListener('change', e => {
      S.sections[e.target.dataset.section] = e.target.checked; save();
    }));
  }
  const setAll = on => { Object.keys(S.sections).forEach(k => { S.sections[k] = on; }); buildGroups(); save(); };
  $('allOn').addEventListener('click', () => setAll(true));
  $('allOff').addEventListener('click', () => setAll(false));

  const lang = $('lang');
  for (const [code, l] of Object.entries(FN.LANGS)) lang.add(new Option(l.name, code));
  lang.value = S.lang;
  lang.addEventListener('change', e => { S.lang = e.target.value; translatePage(); save(); });

  $('autoSearch').checked = S.autoSearch;
  document.querySelector(`input[name=autoOpen][value="${S.autoOpen}"]`).checked = true;
  document.querySelector(`input[name=position][value="${S.position}"]`).checked = true;
  document.querySelector(`input[name=style][value="${S.style}"]`).checked = true;
  document.querySelector(`input[name=accStyle][value="${S.accStyle || 'strip'}"]`).checked = true;
  (document.querySelector(`input[name=theme][value="${S.theme}"]`) || document.querySelector('input[name=theme]')).checked = true;

  $('autoSearch').addEventListener('change', e => { S.autoSearch = e.target.checked; save(); });
  const ALL = ['https://*/*', 'http://*/*'];
  $('allSites').checked = S.allSites && await chrome.permissions.contains({ origins: ALL });
  $('allSites').addEventListener('change', async e => {
    if (e.target.checked) {
      // Must be called straight from the click so Chrome shows its permission prompt.
      const ok = await chrome.permissions.request({ origins: ALL }).catch(() => false);
      if (!ok) { e.target.checked = false; return toast(st('allSitesDenied')); }
    }
    S.allSites = e.target.checked;
    save();
  });
  document.querySelectorAll('input[name=autoOpen]').forEach(r => r.addEventListener('change', e => { S.autoOpen = e.target.value === 'true'; save(); }));
  document.querySelectorAll('input[name=position]').forEach(r => r.addEventListener('change', e => { S.position = e.target.value; save(); }));
  document.querySelectorAll('input[name=style]').forEach(r => r.addEventListener('change', e => { S.style = e.target.value; save(); }));
  document.querySelectorAll('input[name=accStyle]').forEach(r => r.addEventListener('change', e => { S.accStyle = e.target.value; save(); }));
  document.querySelectorAll('input[name=theme]').forEach(r => r.addEventListener('change', e => { S.theme = e.target.value; save(); }));
  // "Help other perfume lovers": one switch for price sharing and the open perfume database together.
  // (Installs from before 1.3 may have only one of the two on; the switch shows on then, and sets both.)
  $('shareAll').checked = !!(S.sharePrices || S.shareFacts);
  $('shareAll').addEventListener('change', e => {
    S.sharePrices = S.shareFacts = e.target.checked;
    S.shareAsked = true;
    save();
  });
  $('themeAuto').checked = !!S.themeAuto;
  $('themeAuto').addEventListener('change', e => { S.themeAuto = e.target.checked; save(); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => save());

  // ---------- keyboard shortcut ----------
  const sc = $('shortcut');
  const showShortcut = () => { sc.value = S.shortcut ? S.shortcut.replace(/\+/g, ' + ') : ''; };
  showShortcut();
  sc.addEventListener('focus', () => { sc.classList.add('rec'); sc.value = ''; sc.placeholder = st('pressKeys'); });
  sc.addEventListener('blur', () => { sc.classList.remove('rec'); sc.placeholder = st('shortcutPh'); showShortcut(); });
  sc.addEventListener('keydown', e => {
    e.preventDefault();
    if (e.key === 'Escape') return sc.blur();
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
    const key = e.code?.startsWith('Key') ? e.code.slice(3) : e.code?.startsWith('Digit') ? e.code.slice(5) : (e.key.length === 1 ? e.key.toUpperCase() : e.key);
    const combo = [e.ctrlKey && 'Ctrl', e.altKey && 'Alt', e.shiftKey && 'Shift', e.metaKey && 'Meta', key].filter(Boolean).join('+');
    // Require a modifier, or a function key, so normal typing never triggers it.
    if (!(e.ctrlKey || e.altKey || e.metaKey) && !/^F\d{1,2}$/.test(key)) return;
    S.shortcut = combo;
    save();
    sc.blur();
  });
  $('clearShortcut').addEventListener('click', () => { S.shortcut = ''; showShortcut(); save(); });

  // ---------- shops ----------
  const BUILT_IN = [...new Set(chrome.runtime.getManifest().content_scripts[0].matches
    .map(m => m.replace(/^https?:\/\/\*\./, '').replace(/\/\*$/, '')))];
  $('builtinShops').innerHTML = BUILT_IN.map(d => `<div>${d}</div>`).join('');
  let customShops = (await chrome.storage.sync.get('customShops')).customShops || [];

  function renderCustomShops() {
    const box = $('customShops');
    box.innerHTML = customShops.length
      ? customShops.map(d => `<span class="shop">${d}<button data-remove="${d}" title="${st('remove')}">×</button></span>`).join('')
      : `<span class="empty">${st('noCustom')}</span>`;
    box.querySelectorAll('[data-remove]').forEach(b => b.addEventListener('click', async () => {
      const d = b.dataset.remove;
      customShops = customShops.filter(x => x !== d);
      await chrome.storage.sync.set({ customShops });
      try { await chrome.permissions.remove({ origins: FN.shopPatterns(d) }); } catch {}
      renderCustomShops();
    }));
  }

  $('addShopForm').addEventListener('submit', async e => {
    e.preventDefault();
    const d = FN.cleanDomain($('shopInput').value);
    if (!d) return toast(st('invalidShop'));
    if (BUILT_IN.some(b => d === b || d.endsWith('.' + b))) return toast(st('alreadyBuiltIn'));
    // Must be called straight from the click so Chrome shows its permission prompt.
    const ok = await chrome.permissions.request({ origins: FN.shopPatterns(d) }).catch(() => false);
    if (!ok) return toast(st('shopDenied'));
    if (!customShops.includes(d)) customShops.push(d);
    await chrome.storage.sync.set({ customShops });
    $('shopInput').value = '';
    renderCustomShops();
    toast(st('shopAdded'));
  });

  // ---------- misc ----------
  $('resetSize').addEventListener('click', async () => { await chrome.storage.local.remove('fn:size'); toast(st('sizeReset')); });
  $('resetAll').addEventListener('click', async () => {
    if (!confirm(st('resetAsk'))) return;
    await chrome.storage.sync.set({ settings: structuredClone(FN.DEFAULTS) });
    await chrome.storage.local.remove('fn:size').catch(() => {});
    toast(st('resetDone'));
    setTimeout(() => location.reload(), 600);
  });

  $('clearCache').addEventListener('click', async () => {
    const all = await chrome.storage.local.get(null);
    const keys = Object.keys(all).filter(k => /^(c|o|n|pc)\d+:/.test(k));
    await chrome.storage.local.remove(keys);
    toast(st('cleared', { n: keys.length }));
  });

  // Keep in sync if settings change elsewhere (e.g. the toolbar menu).
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'sync' && changes.settings) FN.loadSettings().then(s => { const langChanged = s.lang !== S.lang; S = s; $('shareAll').checked = !!(S.sharePrices || S.shareFacts); if (langChanged) translatePage(); updatePreview(); });
    if (area === 'sync' && changes.customShops) { customShops = changes.customShops.newValue || []; renderCustomShops(); }
  });

  translatePage();
  updatePreview();
})();
