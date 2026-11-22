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

  document.getElementById('openSettings').addEventListener('click', () => chrome.runtime.openOptionsPage());
})();
