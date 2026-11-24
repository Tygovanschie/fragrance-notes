// Welcome page: opens once after installing (see background.js). Explains the 🌸 and offers price sharing.
(async () => {
  let S = await FN.loadSettings();
  const st = key => FN_st(S.lang, key);

  document.documentElement.lang = S.lang;
  document.documentElement.dir = ['ar', 'he'].includes(S.lang) ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = st(el.dataset.i18n); });
  document.getElementById('privacy').textContent = FN.t(S.lang, 'privacy');
  document.title = 'Fragrance Notes – ' + st('wel_title');

  // The same setting as Settings → Data. Answering here also means the panel won't ask again.
  const share = document.getElementById('sharePrices');
  share.checked = !!S.sharePrices;
  share.addEventListener('change', async () => {
    S = await FN.loadSettings();
    S.sharePrices = share.checked;
    S.shareAsked = true;
    await chrome.storage.sync.set({ settings: S });
  });

  const facts = document.getElementById('shareFacts');
  facts.checked = !!S.shareFacts;
  facts.addEventListener('change', async () => {
    S = await FN.loadSettings();
    S.shareFacts = facts.checked;
    await chrome.storage.sync.set({ settings: S });
  });

  // Firefox can install the extension without access to the sites (or the user can take it away later).
  // Then ask here; in Chrome and Edge this is granted at install, so the card stays hidden.
  // The check uses the Fragrantica/Bing permissions: Firefox doesn't report shop-site access granted through
  // content scripts via permissions.contains, so checking those would keep the card up after Allow.
  const m = chrome.runtime.getManifest();
  const needed = m.host_permissions || [];
  const origins = [...new Set([...needed, ...(m.content_scripts || []).flatMap(c => c.matches || [])])];
  const perm = document.getElementById('perm');
  const permGo = document.getElementById('permGo');
  const permText = perm.querySelector('p');
  const done = () => { permText.textContent = st('wel_permOk'); permGo.hidden = true; perm.classList.add('ok'); };
  chrome.permissions.contains({ origins: needed }).then(ok => { perm.hidden = ok; }).catch(() => {});
  permGo.addEventListener('click', () => {
    chrome.permissions.request({ origins })
      .then(ok => ok ? done() : null)
      .catch(err => { console.warn('Fragrance Notes: permission request failed', err); });
  });

  document.getElementById('openSettings').addEventListener('click', () => chrome.runtime.openOptionsPage());
})();
