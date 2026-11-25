// Favourites page: the perfumes saved with the ♥ in the panel. Open one to see its details, or tick
// two or three to compare them side by side. Perfumes can be added to or removed from the comparison
// right there. Details come from the same lookup as the panel (cached for 14 days); prices from the
// prices this browser saw on shop pages.
(async () => {
  let S = await FN.loadSettings();
  const $ = id => document.getElementById(id);
  const st = (k, v) => FN_st(S.lang, k, v);
  const { esc } = FN_UI;
  const MAX_CMP = 3;

  document.documentElement.lang = S.lang;
  document.documentElement.dir = ['ar', 'he'].includes(S.lang) ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = st(el.dataset.i18n); });
  document.title = 'Fragrance Notes – ' + st('fav_title');
  $('back').textContent = '← ' + st('fav_back');

  let list = [];
  const picked = new Set();   // ticked in the list
  let shown = [];             // ids in the details / comparison view
  const loaded = new Map();   // id → promise of the perfume data

  // ---------- the list ----------
  async function showList() {
    list = await FN.favs.all();
    [...picked].forEach(id => { if (!list.some(f => f.id === id)) picked.delete(id); });
    $('empty').hidden = list.length > 0;
    $('grid').innerHTML = list.map(f => `
      <li class="card${picked.has(f.id) ? ' sel' : ''}" data-id="${esc(f.id)}">
        <img src="${esc(f.img)}" alt="" loading="lazy">
        <div class="l">
          <b>${esc(f.name)}</b>
          <div class="acts">
            <button class="linkbtn open" type="button">${esc(st('fav_open'))}</button>
            <button class="linkbtn rm" type="button">${esc(st('fav_remove'))}</button>
          </div>
        </div>
        <input class="pick" type="checkbox" aria-label="${esc(st('fav_compare'))}: ${esc(f.name)}"${picked.has(f.id) ? ' checked' : ''}>
      </li>`).join('');
    hideBroken($('grid'));
    paintBar();
  }

  function paintBar() {
    $('cmpBar').hidden = list.length < 2;
    const n = picked.size;
    $('cmpGo').disabled = n < 2 || n > MAX_CMP;
    $('cmpHint').textContent = n > MAX_CMP ? st('fav_max') : st('fav_pick');
    $('cmpGo').textContent = st('fav_compare') + (n ? ` (${n})` : '');
  }

  $('grid').addEventListener('click', async e => {
    const card = e.target.closest('.card');
    if (!card) return;
    const id = card.dataset.id;
    if (e.target.closest('.rm')) { await FN.favs.remove(id); picked.delete(id); return showList(); }
    if (e.target.closest('.open')) return showItems([id]);
  });
  $('grid').addEventListener('change', e => {
    const box = e.target.closest('.pick');
    if (!box) return;
    const card = box.closest('.card');
    if (box.checked) picked.add(card.dataset.id); else picked.delete(card.dataset.id);
    card.classList.toggle('sel', box.checked);
    paintBar();
  });
  $('cmpGo').addEventListener('click', () => showItems([...picked]));
  $('back').addEventListener('click', () => {
    picked.clear(); shown.forEach(id => picked.add(id));
    $('itemView').hidden = true; $('listView').hidden = false;
    showList();
  });

  // A favourite saved or removed in the panel (on another tab) shows up here right away.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'sync' && Object.keys(changes).some(k => k.startsWith('fav:')) && !$('listView').hidden) showList();
  });

  const hideBroken = root => root.querySelectorAll('img').forEach(img => img.addEventListener('error', () => { img.style.visibility = 'hidden'; }));

  // ---------- details / comparison ----------
  const load = f => {
    if (!loaded.has(f.id)) {
      loaded.set(f.id, chrome.runtime.sendMessage({ type: 'lookup', query: f.url, lang: S.lang })
        .then(r => (r && r.data ? r.data : null)).catch(() => null));
    }
    return loaded.get(f.id);
  };

  // Prices this browser saw on shop pages (kept for 90 days by the panel): the cheapest per ml for each perfume.
  async function seenPrices(ids) {
    let all = {};
    try { all = (await chrome.storage.local.get('fn:seen'))['fn:seen'] || {}; } catch {}
    const cutoff = Date.now() - 90 * 864e5;
    const out = {};
    for (const id of ids) {
      const rows = (all[id] || []).filter(o => o.t > cutoff && o.per > 0 && o.ml > 0);
      if (rows.length) out[id] = rows.reduce((a, b) => (b.per < a.per ? b : a));
    }
    return out;
  }

  // Picker for another favourite: in the details view and as the last column of the comparison.
  const addSelect = () => {
    const others = list.filter(f => !shown.includes(f.id));
    if (!others.length || shown.length >= MAX_CMP) return '';
    return `<select class="add" aria-label="${esc(st('fav_add'))}"><option value="">${esc(st('fav_add'))}</option>${
      others.map(f => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join('')}</select>`;
  };

  async function showItems(ids) {
    shown = ids.filter(id => list.some(f => f.id === id)).slice(0, MAX_CMP);
    if (!shown.length) { $('itemView').hidden = true; $('listView').hidden = false; return showList(); }
    const favs = shown.map(id => list.find(f => f.id === id));
    $('listView').hidden = true;
    $('itemView').hidden = false;
    const body = $('itemBody');
    if (!body.querySelector('table, .detail')) body.innerHTML = `<p class="loading">${esc(st('fav_loading'))}</p>`;
    const [data, prices] = await Promise.all([Promise.all(favs.map(load)), seenPrices(shown)]);
    if ($('itemView').hidden || favs.map(f => f.id).join() !== shown.join()) return;   // changed meanwhile
    if (favs.length === 1) { showDetail(body, data[0], prices[favs[0].id]); alertTools(body, favs[0]); }
    else showCompare(body, favs, data, prices);
    body.querySelector('select.add')?.addEventListener('change', e => { if (e.target.value) showItems([...shown, e.target.value]); });
  }

  const priceText = p => {
    const cur = p.currency || 'EUR';
    const money = v => { try { return new Intl.NumberFormat(S.lang, { style: 'currency', currency: cur }).format(v); } catch { return `${v.toFixed(2)} ${cur}`; } };
    return { bottle: money(p.per * p.ml), perMl: money(p.per), ml: Math.round(p.ml) };
  };

  // Price alert for one favourite (checked every six hours in background.js). It uses the prices other users
  // share, so it needs "Help other perfume lovers"; notifications need an optional permission, asked on "Set".
  async function alertTools(body, fav) {
    const tools = body.querySelector('.detail-tools');
    if (!tools || !fav) return;
    const box = document.createElement('div');
    box.className = 'alert';
    tools.append(box);
    const key = 'alert:' + fav.id;
    const money = (v, cur) => { try { return new Intl.NumberFormat(S.lang, { style: 'currency', currency: cur }).format(v); } catch { return `${v.toFixed(2)} ${cur}`; } };
    if (!S.sharePrices) { box.innerHTML = `<span class="muted">🔔 ${esc(st('al_needShare'))}</span>`; return; }
    const data = await chrome.runtime.sendMessage({ type: 'community', perfumeId: fav.id }).catch(() => null);
    const sizes = (data?.sizes || []).filter(s => Object.keys(s.lows || {}).length).sort((a, b) => a.ml - b.ml);
    const cur = data?.currency || 'EUR';
    const saved = (await chrome.storage.sync.get(key).catch(() => ({})))[key];
    const showSaved = a => {
      box.innerHTML = `<span>🔔 ${esc(st('al_saved', { ml: Math.round(a.ml), price: money(a.price, a.cur || cur) }))}</span>
        <button class="btn quiet" type="button">${esc(st('al_remove'))}</button>`;
      box.querySelector('button').addEventListener('click', async () => { await chrome.storage.sync.remove(key).catch(() => {}); showForm(); });
    };
    const showForm = () => {
      if (!sizes.length) { box.innerHTML = `<span class="muted">🔔 ${esc(st('al_noSizes'))}</span>`; return; }
      const near = sizes.reduce((a, b) => (Math.abs(b.ml - 100) < Math.abs(a.ml - 100) ? b : a));
      const low = s => Math.min(...Object.values(s.lows));
      box.innerHTML = `<form class="alert-form"><b>🔔 ${esc(st('al_title'))}</b>
        <select aria-label="${esc(st('al_size'))}">${sizes.map(s => `<option value="${s.ml}"${s === near ? ' selected' : ''}>${s.ml} ml · ${esc(money(low(s), cur))}</option>`).join('')}</select>
        <label>${esc(st('al_below'))} <input type="number" min="1" step="0.01" required value="${Math.floor(low(near) * 0.9)}"></label>
        <button class="btn primary">${esc(st('al_save'))}</button></form>`;
      const form = box.querySelector('form');
      form.querySelector('select').addEventListener('change', e => {
        const s = sizes.find(x => String(x.ml) === e.target.value);
        if (s) form.querySelector('input').value = Math.floor(low(s) * 0.9);
      });
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const ok = await chrome.permissions.request({ permissions: ['notifications'] }).catch(() => false);
        if (!ok) return;
        const a = { ml: Number(form.querySelector('select').value), price: Number(form.querySelector('input').value), cur, t: Date.now() };
        if (!(a.ml > 0 && a.price > 0)) return;
        await chrome.storage.sync.set({ [key]: a }).catch(() => {});
        showSaved(a);
      });
    };
    if (saved) showSaved(saved); else showForm();
  }

  // One perfume: the same view as the panel on a shop page, with a picker to compare it with another.
  function showDetail(body, d, price) {
    if (!d) { body.innerHTML = `<p class="failed">${esc(st('fav_failed'))}</p>`; return; }
    const p = price && priceText(price);
    body.innerHTML = `<div class="detail-tools">${addSelect()}${p ? `<span class="seen">${esc(st('fav_price'))}: <b>${esc(p.bottle)}</b> · ${p.ml} ml ${esc(st('fav_at'))} <a href="${esc(price.url)}" target="_blank" rel="noopener">${esc(price.host)}</a></span>` : ''}</div>
      <div class="detail"><div id="detailHost"></div></div>`;
    const root = $('detailHost').attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${FN_UI.CSS}
        .panel { width:440px; max-width:calc(100vw - 40px); max-height:none; animation:none; }
        .rz, .head .gear, .head .x, .head .srch, .head .hfav { display:none; }
      </style>
      <style>${FN_UI.themeCss(FN.resolveTheme(S))}</style>
      <div class="panel">${FN_UI.panelHtml}</div>`;
    root.querySelector('form').remove();
    const inner = root.querySelector('.body');
    inner.innerHTML = FN_UI.renderBody(d, S, { allowRemote: true, noRefresh: true });
    FN_UI.localizeChrome(root, S.lang);
    // Notes open their description, as in the panel.
    inner.addEventListener('click', e => { const chip = e.target.closest('.chip.nb'); if (chip) toggleNote(chip, chip.closest('.tier') || chip.parentElement); });
  }

  // ---------- note descriptions (click a note) ----------
  const noteCache = new Map();
  function toggleNote(chip, after, asRow = false) {
    const scope = chip.getRootNode();
    const open = scope.querySelector('.notepop');
    const same = chip.classList.contains('on');
    scope.querySelectorAll('.chip.nb.on').forEach(c => c.classList.remove('on'));
    (open?.closest('tr.noterow') || open)?.remove();
    if (same) return;
    chip.classList.add('on');
    const { note: url, name, img } = chip.dataset;
    const pop = document.createElement('div');
    pop.className = 'notepop';
    const fill = info => {
      pop.innerHTML = `${img ? `<img src="${esc(img)}" alt="">` : '<span></span>'}<div><div class="nn"><span>${esc(name)}${
        info?.latin ? ` <i class="lat">${esc(info.latin)}</i>` : ''}</span><a href="${esc(url)}" target="_blank" rel="noopener">Fragrantica ↗</a></div>${
        !info ? `<span class="muted">${esc(st('fav_loading'))}</span>`
        : (info.facts || []).map(f => `<div class="nl">${esc(f.label)}</div><div>${esc(f.text)}</div>`).join('')}</div>`;
    };
    fill(noteCache.get(url));
    if (asRow) {
      const tr = document.createElement('tr');
      tr.className = 'noterow';
      tr.innerHTML = `<th></th><td colspan="${shown.length + 1}"></td>`;
      tr.lastElementChild.appendChild(pop);
      after.after(tr);
    } else after.appendChild(pop);
    if (!noteCache.has(url)) {
      chrome.runtime.sendMessage({ type: 'note', url }).then(info => {
        noteCache.set(url, info || {});
        if (pop.isConnected) fill(noteCache.get(url));
      }).catch(() => { noteCache.set(url, {}); if (pop.isConnected) fill({}); });
    }
  }

  // ---------- comparison ----------
  const safeColor = c => (/^(rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)|#[0-9a-f]{3,8})$/i.test(String(c || '').trim()) ? c : 'var(--soft)');
  const okImg = src => /^data:image\//.test(src || '') || /^https:\/\/fimgs\.net\//.test(src || '');

  // Notes count as the same when their words match, or when one is a more precise name of the other
  // ("Bergamot" and "Calabrian Bergamot"). Fragrantica uses both for the same ingredient.
  const noteWords = n => String(n?.name || n || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .split(/[^a-z0-9Ѐ-ӿͰ-Ͽ֐-׿؀-ۿ぀-ヿ一-鿿가-힯]+/).filter(Boolean);
  const sameNote = (a, b) => {
    const A = noteWords(a), B = noteWords(b);
    if (!A.length || !B.length) return false;
    const [short, long] = A.length <= B.length ? [A, B] : [B, A];
    const s = short.join(' ');
    for (let i = 0; i + short.length <= long.length; i++) if (long.slice(i, i + short.length).join(' ') === s) return true;
    return false;
  };
  const notesOf = d => (d?.notes || []).flatMap(t => t.names);

  // Where the average vote sits: 1 … number of options (e.g. 3.4 of 5).
  const voteScore = v => {
    if (!v?.rows?.length || !v.total) return null;
    const mean = v.rows.reduce((s, r, i) => s + (i + 1) * r.n, 0) / v.total;
    return { mean, of: v.rows.length, top: v.top, rows: v.rows, total: v.total };
  };

  function showCompare(body, favs, data, prices) {
    const L = data.find(d => d?.labels)?.labels || {};
    const T = k => L[k] || FN.t(S.lang, k);
    const n = favs.length;
    const cols = (fn, cls = '') => favs.map((f, i) => `<td${cls ? ` class="${cls}"` : ''}>${data[i] ? fn(data[i], i, f) : `<span class="none">${esc(st('fav_failed'))}</span>`}</td>`).join('');
    const row = (label, fn, cls = '') => `<tr${cls ? ` class="${cls}"` : ''}><th scope="row">${esc(label)}</th>${cols(fn)}<td class="slot"></td></tr>`;
    const section = label => `<tr class="sec"><th colspan="${n + 2}">${esc(label)}</th></tr>`;

    // Notes that all compared perfumes share.
    const firstNotes = notesOf(data[0]);
    const common = data.every(Boolean) ? firstNotes.filter(a => data.slice(1).every(d => notesOf(d).some(b => sameNote(a, b)))) : [];
    const isCommon = note => common.some(c => sameNote(c, note));
    const noteChip = note => {
      const url = note.url || '';
      const img = okImg(note.img) ? note.img : '';
      return `<span class="chip nchip${isCommon(note) ? ' shared' : ''}${url ? ' nb' : ''}"${url ? ` data-note="${esc(url)}" data-name="${esc(note.name)}" data-img="${esc(img)}" role="button" tabindex="0"` : ''}>${
        img ? `<img src="${esc(img)}" alt="">` : ''}${esc(note.name)}</span>`;
    };

    const rows = [];
    // Who
    rows.push(`<tr class="who-row"><th></th>${favs.map((f, i) => {
      const d = data[i];
      const meta = d ? [d.year, d.audience, d.rating && `★ ${d.rating}`].filter(Boolean).map(esc).join(' · ') : '';
      return `<td class="who" data-id="${esc(f.id)}"><button class="x" type="button" title="${esc(st('fav_rmCmp'))}" aria-label="${esc(st('fav_rmCmp'))}">×</button>
        <img src="${esc(f.img)}" alt=""><a href="${esc(d?.url || f.url)}" target="_blank" rel="noopener">${esc(d?.title || f.name)}</a>${meta ? `<small>${meta}</small>` : ''}</td>`;
    }).join('')}<td class="slot">${addSelect()}</td></tr>`);

    // Price
    const seen = favs.map(f => prices[f.id]);
    rows.push(row(st('fav_price'), (d, i) => {
      const p = seen[i];
      if (!p) return `<span class="none">${esc(st('fav_noPrice'))}</span>`;
      const t = priceText(p);
      return `<div class="price"><b>${esc(t.bottle)}</b> · ${t.ml} ml</div><small>${esc(t.perMl)}/ml · ${esc(st('fav_at'))} <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.host)}</a></small>`;
    }));

    // Accords: one line per accord, a bar for each perfume, so the differences are easy to see.
    const accNames = [];
    data.forEach(d => (d?.accords || []).forEach(a => { if (!accNames.some(x => x.toLowerCase() === a.name.toLowerCase())) accNames.push(a.name); }));
    const accOf = (d, name) => (d?.accords || []).find(a => a.name.toLowerCase() === name.toLowerCase());
    const accRank = name => Math.max(...data.map(d => accOf(d, name)?.width || 0));
    rows.push(section(T('accords')));
    accNames.sort((a, b) => accRank(b) - accRank(a)).slice(0, 10).forEach(name => {
      const color = safeColor(data.map(d => accOf(d, name)).find(Boolean)?.bg);
      rows.push(`<tr class="acc"><th scope="row"><i style="background:${color}"></i>${esc(name)}</th>${cols(d => {
        const a = accOf(d, name);
        return a ? `<div class="abar"><span style="width:${Math.max(4, Math.round(a.width))}%;background:${color}"></span></div>` : '<span class="none">–</span>';
      })}<td class="slot"></td></tr>`);
    });

    // Notes per layer, with pictures; shared notes highlighted. Click a note for its description.
    const tiers = Math.max(...data.map(d => d?.notes?.length || 0));
    rows.push(section(FN.t(S.lang, 'notes')));
    for (let t = 0; t < tiers; t++) {
      const label = data.find(d => d?.notes?.[t]?.label)?.notes[t].label || FN.t(S.lang, 'notes');
      rows.push(row(label, d => d.notes?.[t] ? `<div class="chips">${d.notes[t].names.map(noteChip).join('')}</div>` : '<span class="none">–</span>', 'notes'));
    }

    // Votes: average score on the scale, the spread of the votes, and how much higher the best one is.
    const voteRow = (key, v, showLead = true) => {
      const scores = data.map(d => voteScore(d?.[v]));
      // Differences are worked out from the rounded scores that are shown, so 3.6 vs 3.6 never says "+0.1".
      const r1 = x => Math.round(x * 10) / 10;
      const vals = scores.filter(Boolean).map(s => r1(s.mean));
      const lo = vals.length > 1 ? Math.min(...vals) : null;
      rows.push(row(T(key), (d, i) => {
        const s = scores[i];
        if (!s) return '<span class="none">–</span>';
        const pct = (s.mean - 1) / Math.max(s.of - 1, 1) * 100;
        // Every perfume above the lowest shows how much higher it scores than the lowest.
        const diff = lo === null ? 0 : Math.round((r1(s.mean) - lo) * 10) / 10;
        const lead = showLead && diff >= 0.1 ? `<span class="tag">+${diff.toFixed(1)}</span>` : '';
        const spread = s.rows.map((r, k) => `<i style="flex:${r.n};opacity:${(0.25 + 0.75 * k / Math.max(s.rows.length - 1, 1)).toFixed(2)}" title="${esc(r.label)}: ${Math.round(r.n / s.total * 100)}%"></i>`).join('');
        return `<div class="score"><b>${r1(s.mean).toFixed(1)}</b><span class="of">/ ${s.of}</span>${lead}</div>
          <div class="scale"><span style="inset-inline-start:${pct.toFixed(1)}%"></span></div>
          <div class="spread">${spread}</div><small>${esc(s.top)}</small>`;
      }));
    };
    voteRow('longevity', 'longevity');
    voteRow('sillage', 'sillage');
    voteRow('priceValue', 'priceValue');
    voteRow('gender', 'gender', false);

    // When to wear: the seasons and day/night as small bars.
    const wearRow = (label, pick) => rows.push(row(label, d => {
      const w = pick(d.wear || []);
      if (!w.length) return '<span class="none">–</span>';
      const max = Math.max(...w.map(x => x.n), 1);
      return `<div class="wear">${w.map(x => `<div class="wl${x.n === max ? ' hi' : ''}"><span>${esc(x.label)}</span><div class="abar"><span style="width:${Math.round(x.n / max * 100)}%"></span></div></div>`).join('')}</div>`;
    }));
    rows.push(section(T('wear')));
    wearRow(st('fav_season'), w => w.slice(0, 4));
    wearRow(st('fav_time'), w => w.slice(4, 6));

    body.innerHTML = `<div class="cmp-wrap"><table class="cmp cols${n}"><colgroup><col class="lab">${favs.map(() => '<col>').join('')}<col class="slotcol"></colgroup>${rows.join('')}</table></div>`;
    hideBroken(body);
    const table = body.querySelector('table');
    table.addEventListener('click', e => {
      const x = e.target.closest('.who .x');
      if (x) return showItems(shown.filter(id => id !== x.closest('.who').dataset.id));
      const chip = e.target.closest('.chip.nb');
      if (chip) toggleNote(chip, chip.closest('tr'), true);
    });
    table.addEventListener('keydown', e => {
      const chip = e.target.closest('.chip.nb');
      if (chip && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleNote(chip, chip.closest('tr'), true); }
    });
  }

  // Opened from a price-alert notification (favourites.html#<id>): straight to that perfume.
  await showList();
  const fromAlert = location.hash.slice(1);
  if (/^\d+$/.test(fromAlert)) showItems([fromAlert]);
})();
