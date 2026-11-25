// Welcome page: opens once after installing (see background.js). Explains the 🌸 and offers price sharing.
(async () => {
  let S = await FN.loadSettings();
  const st = key => FN_st(S.lang, key);

  document.documentElement.lang = S.lang;
  document.documentElement.dir = ['ar', 'he'].includes(S.lang) ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = st(el.dataset.i18n); });
  document.getElementById('privacy').textContent = FN.t(S.lang, 'privacy');
  if (S.lang === 'nl') document.getElementById('seeDb').href = 'https://fragrancenotes.app/nl/database';
  document.title = 'Fragrance Notes – ' + st('wel_title');

  // One clear choice for both kinds of sharing (like the one switch in Settings → Data). Nothing is on until
  // the user picks "Yes". Answering here also means the panel and the toolbar menu won't ask again.
  const state = document.getElementById('choiceState');
  const btns = document.getElementById('choiceBtns');
  const showState = () => {
    if (!S.shareAsked) return;
    const on = S.sharePrices || S.shareFacts;
    state.textContent = st(on ? 'wel_saidYes' : 'wel_saidNo');
    state.hidden = false;
    btns.hidden = true;
  };
  const choose = async on => {
    S = await FN.loadSettings();
    S.sharePrices = on;
    S.shareFacts = on;
    S.shareAsked = true;
    await chrome.storage.sync.set({ settings: S });
    if (!on) chrome.storage.local.set({ 'fn:shareDeclined': true }).catch(() => {});
    showState();
  };
  document.getElementById('choiceYes').addEventListener('click', () => choose(true));
  document.getElementById('choiceNo').addEventListener('click', () => choose(false));
  showState();

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
