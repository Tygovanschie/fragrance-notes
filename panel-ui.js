// Panel look and rendering, shared by the in-page panel and the settings preview.
(() => {
  const CSS = `
    :host { all: initial; }
    [hidden] { display:none !important; }
    * { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }

    .pill { width:44px; height:44px; display:grid; place-items:center; padding:0;
      border-radius:50%; border:0; background:var(--head); line-height:0; cursor:pointer;
      box-shadow:0 6px 20px rgba(0,0,0,.25); transition:transform .15s; }
    .pill:hover { transform:scale(1.08); }
    .pill svg, .head svg { display:block; flex:none; }
    .pill.loading { animation:pulse 1.2s ease-in-out infinite; }
    @keyframes pulse { 0%,100% { box-shadow:0 6px 20px rgba(0,0,0,.25), 0 0 0 0 rgba(245,143,184,.6); }
                       50% { box-shadow:0 6px 20px rgba(0,0,0,.25), 0 0 0 6px rgba(245,143,184,0); } }

    .panel { position:relative; width:360px; height:auto; max-height:min(820px, calc(100vh - 90px));
      min-width:280px; min-height:220px; display:flex; flex-direction:column; animation:drop .18s ease-out;
      background:var(--bg); color:var(--fg); border-radius:14px; box-shadow:0 12px 40px rgba(0,0,0,.28);
      overflow:hidden; font-size:13px; line-height:1.4; }
    .panel.sized { max-height:calc(100vh - 100px); }
    @keyframes drop { from { opacity:0; transform:translateY(8px); } }

    /* Invisible resize zone on the panel's inner corner (away from the screen corner). */
    .rz { position:absolute; width:16px; height:16px; z-index:3; touch-action:none; }
    .rz.tl { top:0; left:0; cursor:nwse-resize; }
    .rz.tr { top:0; right:0; cursor:nesw-resize; }
    .rz.bl { bottom:0; left:0; cursor:nesw-resize; }
    .rz.br { bottom:0; right:0; cursor:nwse-resize; }

    .head { display:flex; align-items:center; gap:8px; padding:9px 10px 9px 14px;
      background:var(--head); color:var(--headFg); font-size:13px; font-weight:600; flex:none; }
    .head .t { flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .gear { background:none; border:0; color:inherit; opacity:.7; cursor:pointer; padding:3px; border-radius:6px; line-height:0; }
    .gear:hover { opacity:1; background:rgba(127,127,127,.18); }

    form { display:flex; gap:6px; padding:10px 16px; flex:none; background:var(--card); }
    input { flex:1; min-width:0; padding:7px 9px; border:1px solid var(--inputBorder); border-radius:8px; font-size:12px; color:var(--fg); background:var(--input); }
    form button { padding:7px 10px; border:0; border-radius:8px; background:var(--accent); color:var(--onAccent); font-size:12px; font-weight:600; cursor:pointer; }
    .body { flex:1; overflow:auto; padding:12px 16px 16px; }

    h2 { font-size:15px; margin:0 0 2px; }
    h3 { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--label); margin:14px 0 6px; overflow-wrap:break-word; }
    a { color:var(--accent); text-decoration:none; }
    a:hover { text-decoration:underline; }
    .muted { color:var(--muted); font-size:12px; }
    .meta { display:flex; flex-wrap:wrap; gap:4px 10px; color:var(--muted); font-size:12px; min-width:0; }
    .tier b { overflow-wrap:break-word; }
    .chip { max-width:100%; }

    .accs { display:flex; flex-direction:column; gap:3px; }
    .accbar { height:20px; display:flex; align-items:center; padding:0 8px; border-radius:0 6px 6px 0;
      font-size:11px; font-weight:600; text-transform:lowercase; white-space:nowrap; overflow:hidden; min-width:fit-content; max-width:100%; }
    [dir=rtl] .accbar { border-radius:6px 0 0 6px; }
    .simple .accbar { background:var(--chip) !important; color:var(--fg) !important; border-left:3px solid var(--accent); font-weight:500; }
    /* Simple style: same layout, quieter. */
    .simple .wb { background:var(--chip); color:var(--fg); }
    .simple .wc .fill, .simple .wc.hi .fill { background:var(--soft); }
    .simple .wc.hi .fill { background:var(--accent); opacity:.75; }
    .simple .pcol .pi { background:var(--chip) !important; color:var(--muted); }
    .simple .gtrack { background:var(--chip); }
    .simple .astrip i, .simple .achip i { filter:grayscale(.85) opacity(.7); }
    .simple .tile { background:var(--chip); backdrop-filter:none; }
    .simple .hero { background:var(--card); }

    .tier { margin:4px 0 8px; }
    .tier b { font-size:12px; display:block; margin-bottom:3px; }
    .chips { display:flex; flex-wrap:wrap; gap:4px; }
    .chip { display:inline-flex; align-items:center; gap:5px; padding:2px 9px 2px 2px; border-radius:999px; background:var(--chip); font-size:12px; }
    .chip.noimg { padding:3px 9px; }
    .chip img { width:22px; height:22px; border-radius:50%; object-fit:cover; background:#fff; flex:none; }

    .wear { display:grid; grid-template-columns:repeat(4, 1fr) 6px repeat(2, 1fr); gap:6px; align-items:end; }
    .wsep { align-self:stretch; width:1px; background:var(--border); margin:0 auto; }
    .wbest { display:flex; flex-wrap:wrap; gap:6px; margin:-2px 0 8px; }
    .wb { background:var(--accent); color:var(--onAccent, #fff); border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600; }
    .wb span { display:inline-block; }
    .wb span::first-letter { text-transform:uppercase; }
    .wc .wp { display:block; font-size:10px; font-variant-numeric:tabular-nums; margin-bottom:2px; }
    .wc .wi { display:block; font-size:14px; line-height:1; margin:2px 0 1px; }
    .wc .wl { display:block; }
    .wc .wl::first-letter { text-transform:uppercase; }
    .pc { display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px 18px; }
    .pcol b { display:block; font-size:12px; margin-bottom:3px; }
    .pcol ul { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:4px; }
    .pcol li { display:grid; grid-template-columns:16px 1fr auto; gap:6px; align-items:start; font-size:12px; line-height:1.35; }
    .pcol .pi { width:16px; height:16px; border-radius:50%; display:grid; place-items:center; color:#fff; margin-top:0; }
    .pcol .pi svg { display:block; }
    .pcol .pro .pi { background:#3f9b62; }
    .pcol .con .pi { background:#c4553f; }
    .pcol em { font-style:normal; font-size:10.5px; color:var(--muted); font-variant-numeric:tabular-nums; margin-top:1px; }
    .chip.nb { cursor:pointer; transition:box-shadow .12s; }
    .chip.nb:hover, .chip.nb.on { box-shadow:0 0 0 2px var(--accent); }
    .notepop { margin:6px 0 2px; padding:10px; border-radius:10px; background:var(--card); border:1px solid var(--border); display:grid; grid-template-columns:48px 1fr; gap:10px; font-size:12px; line-height:1.45; }
    .notepop img { width:48px; height:48px; border-radius:10px; object-fit:cover; background:#fff; }
    .notepop .nn { font-weight:700; font-size:13px; display:flex; justify-content:space-between; gap:8px; }
    .notepop .nn a { font-weight:400; font-size:11px; color:var(--muted); text-decoration:none; }
    .notepop .nn a:hover { color:var(--accent); }
    .notepop .nl { color:var(--label); font-size:10px; text-transform:uppercase; letter-spacing:.05em; font-weight:700; margin-top:5px; }
    .notepop .lat { font-weight:400; color:var(--muted); font-size:11.5px; }
    .notepop .nl + div { margin-bottom:2px; }
    .wc { text-align:center; font-size:10px; line-height:1.2; color:var(--muted); min-width:0; overflow-wrap:anywhere; hyphens:auto; }
    .wc::first-letter { text-transform:uppercase; }
    .wc .track { height:46px; background:var(--chip); border-radius:6px; display:flex; align-items:flex-end; overflow:hidden; margin-bottom:3px; }
    .wc .fill { width:100%; background:var(--soft); border-radius:6px 6px 0 0; }
    .wc.hi .fill { background:var(--accent); }
    .wc.hi { color:var(--fg); font-weight:600; }

    /* All vote blocks flow in one grid: 2 columns at the default width, more when wider,
       and the remaining blocks close up neatly when some are turned off. */
    /* Each block is one grid so labels, bars and counts line up across its rows. */
    .vote { min-width:0; display:grid; grid-template-columns:minmax(0, max-content) minmax(22px, 1fr) auto; column-gap:6px; row-gap:2px; align-items:center; align-content:start; }
    .vote h3, .vote b { grid-column:1 / -1; }
    .vote b { font-size:13px; margin-bottom:3px; overflow-wrap:break-word; }
    .vote b::first-letter { text-transform:uppercase; }
    .vrow { display:contents; font-size:11px; color:var(--muted); }
    .vrow > * { font-size:11px; color:var(--muted); }
    /* Long labels (e.g. "enttäuschende Haltbarkeit") wrap instead of running into the bars. */
    .vrow span { white-space:normal; line-height:1.2; overflow-wrap:break-word; hyphens:auto; min-width:0; }
    .vrow .bar { height:5px; border-radius:3px; background:var(--chip); overflow:hidden; display:block; }
    .vrow .bar i { display:block; height:100%; border-radius:3px; background:var(--soft); }
    .vrow.top .bar i { background:var(--accent); }
    .vrow em { font-style:normal; text-align:right; font-variant-numeric:tabular-nums; min-width:2.4em; }

    .top-info { display:flex; gap:12px; align-items:flex-start; }
    .top-info .photo { width:58px; height:72px; flex:none; border-radius:8px; background:#fff; object-fit:contain; padding:3px; border:1px solid var(--border); }
    .top-info .ti { min-width:0; flex:1; }

    .sims { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:6px; }
    .simc { display:flex; align-items:center; gap:8px; padding:6px 8px; border-radius:10px; background:var(--card); color:var(--fg); min-width:0; }
    .simc:hover { background:var(--chip); text-decoration:none; }
    .simc img { width:30px; height:30px; object-fit:contain; flex:none; border-radius:4px; background:#fff; }
    .simc .t { min-width:0; display:flex; flex-direction:column; }
    .simc .n { font-size:12px; font-weight:600; line-height:1.25; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
    .simc .b { display:flex; align-items:center; gap:4px; min-width:0; font-size:11px; color:var(--muted); }
    .simc .bn { min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .simc .b .badge { flex:none; margin:0; }

    .badge { display:inline-block; margin-inline-start:4px; padding:0 5px; border-radius:4px; background:var(--accent); color:var(--onAccent);
      font-size:9.5px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; vertical-align:1px; }
    .dupes .simc { background:var(--chip); }

    .perml { display:grid; grid-template-columns:auto auto 1fr; min-width:0; gap:3px 12px; font-size:12px; align-items:baseline; }
    .perml .ml { font-weight:600; }
    .perml .pp { color:var(--muted); text-align:end; font-variant-numeric:tabular-nums; }
    .perml .best { color:var(--accent); font-weight:700; }
    .perml .best .badge { vertical-align:0; margin-inline:0 6px; }
    .perml.others { grid-template-columns:minmax(0,1fr) auto auto auto; }
    .perml.others a.ml { color:var(--fg); text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500; }
    .perml.others a.ml:hover { color:var(--accent); text-decoration:underline; }
    .perml .sz, .perml .pr { white-space:nowrap; color:var(--muted); }
    .spin.sm { width:11px; height:11px; border-width:2px; margin:0; }
    .more { margin-top:4px; border:0; background:none; color:var(--accent); cursor:pointer; font:inherit; font-size:12px; padding:0; }
    .cands { display:flex; flex-direction:column; gap:6px; margin-top:8px; }
    .cand { display:flex; align-items:center; gap:10px; padding:6px 8px; border-radius:10px; background:var(--card); border:1px solid var(--border); cursor:pointer; text-align:start; font:inherit; color:var(--fg); }
    .cand:hover { outline:2px solid var(--accent); }
    .cand img { width:30px; height:40px; object-fit:contain; border-radius:4px; background:#fff; flex:none; }
    .cand .n { font-weight:600; display:block; }
    .cand .b { color:var(--muted); font-size:11.5px; text-transform:capitalize; }


    /* 6. Slim header: the search field only shows after clicking the magnifier (or when nothing was found). */
    .panel:not(.searching) form { display:none; }
    .srch { background:none; border:0; color:inherit; opacity:.7; cursor:pointer; padding:3px; border-radius:6px; line-height:0; }
    .srch:hover, .panel.searching .srch { opacity:1; background:rgba(127,127,127,.18); }

    /* 4. Hero: name and photo on a soft wash of the perfume's own accord colours. */
    .hero { margin:-12px -14px 0; padding:14px 14px 12px; background:var(--card); border-bottom:1px solid var(--border); }
    .hero .photo { box-shadow:0 2px 8px rgba(0,0,0,.08); }

    /* 1. Summary tiles. */
    .tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(128px, 1fr)); gap:6px; margin-top:10px; }
    .tile { min-width:0; padding:6px 9px; border-radius:10px; background:color-mix(in srgb, var(--bg) 78%, transparent);
      display:flex; flex-direction:column; gap:1px; backdrop-filter:blur(4px); }
    .tile b { font-size:12.5px; line-height:1.25; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .tile b::first-letter { text-transform:uppercase; }
    .tile .ic { letter-spacing:3px; font-size:15px; line-height:1.1; }
    .tile span { text-transform:none; }
    .tile span::first-letter { text-transform:uppercase; }
    .tile span { font-size:10px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

    /* 3. Accord strip. */
    .astrip { display:flex; height:14px; border-radius:7px; overflow:hidden; gap:2px; }
    .astrip i { display:block; min-width:6px; }
    .achips { display:flex; flex-wrap:wrap; gap:4px 10px; margin-top:7px; }
    .achip { display:inline-flex; align-items:center; gap:5px; font-size:11.5px; }
    .achip i { width:9px; height:9px; border-radius:50%; flex:none; }

    /* 5. Notes pyramid. */
    .pyr { display:flex; flex-direction:column; gap:10px; }
    .pyr .tier { margin:0; }
    /* Tier name as a quiet line above its notes, with a hairline running to the edge. */
    .pyr .tl { display:flex; align-items:center; gap:8px; margin-bottom:5px; font-size:11px; color:var(--muted); }
    .pyr .tl::after { content:''; flex:1; height:1px; background:var(--border); }
    .pyr .tl span::first-letter { text-transform:uppercase; }
    .pyr .notepop { margin:6px 0 0; }
    .pyr .chips { align-content:center; }
    .pyr .chip { padding:2px 10px 2px 2px; font-size:12px; }
    .pyr .chip img { width:28px; height:28px; }
    .pyr .chip.noimg { padding:5px 10px; }

    /* 2. Vote lines. */
    .votes { display:flex; flex-direction:column; gap:0; margin-top:12px; border-top:1px solid var(--border); }
    details.vline { border-bottom:1px solid var(--border); }
    details.vline > summary { list-style:none; cursor:pointer; display:grid; grid-template-columns:minmax(0, 1fr) auto minmax(0, 1.1fr) 10px;
      align-items:center; gap:10px; padding:8px 0; font-size:12px; }
    details.vline > summary::-webkit-details-marker { display:none; }
    details.vline > summary::after { content:'▾'; color:var(--muted); font-size:10px; transition:transform .15s; }
    details.vline[open] > summary::after { transform:rotate(180deg); }
    .vline .vt { color:var(--label); font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; overflow-wrap:break-word; hyphens:auto; line-height:1.25; }
    .vline summary b { font-size:12.5px; overflow-wrap:break-word; hyphens:auto; line-height:1.25; text-align:end; }
    .vline summary b::first-letter { text-transform:uppercase; }
    .dots { display:inline-flex; gap:3px; width:68px; }
    .dots i { width:8px; height:8px; border-radius:50%; background:var(--chip); box-shadow:inset 0 0 0 1px var(--border); }
    .dots i.f { background:var(--accent); box-shadow:none; }
    details.vline .vote { padding:0 0 10px; }
    .gscale { display:inline-flex; align-items:center; gap:4px; width:68px; }
    .gscale .gs { font-size:11px; color:var(--muted); line-height:1; }
    .gtrack { position:relative; flex:1; height:6px; border-radius:3px;
      background:linear-gradient(90deg, #e58bb4, #c9b6d9 50%, #7fa6d9); }
    .gtrack i { position:absolute; top:50%; width:11px; height:11px; border-radius:50%; background:var(--bg);
      border:2px solid var(--fg); transform:translate(-50%, -50%); }

    /* Similar perfumes and dupes: three small bottle cards side by side. */
    .sims.row3 { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; }
    .row3 .simc { flex-direction:column; align-items:center; text-align:center; gap:5px; padding:8px 6px; min-width:0; overflow:hidden; }
    .row3 .simc img { width:52px; height:52px; border-radius:8px; }
    .row3 .simc .t { align-items:center; width:100%; min-width:0; }
    .row3 .simc .n { font-size:11.5px; width:100%; overflow-wrap:anywhere; }
    .row3 .simc .b { flex-direction:column; gap:3px; width:100%; font-size:10.5px; }
    .row3 .simc .bn { display:block; width:100%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

    /* Loading placeholder. */
    .sk { display:block; border-radius:6px; background:linear-gradient(90deg, var(--chip) 0%, var(--border) 50%, var(--chip) 100%);
      background-size:200% 100%; animation:shimmer 1.3s ease-in-out infinite; }
    @keyframes shimmer { from { background-position:100% 0; } to { background-position:-100% 0; } }
    .skel { display:flex; flex-direction:column; gap:6px; }
    .sk-hero { display:flex; gap:12px; margin-bottom:6px; }
    .sk-hero > div { flex:1; display:flex; flex-direction:column; gap:8px; padding-top:4px; }
    .sk-photo { width:58px; height:72px; border-radius:8px; flex:none; }
    .sk-l { height:12px; }
    .w70 { width:70%; } .w40 { width:40%; }
    .sk-tiles { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:10px; }
    .sk-tiles .sk { height:38px; border-radius:10px; }
    .sk-h { width:110px; height:10px; margin:12px 0 4px; }
    .sk-bar { height:18px; }
    .sk-chips { display:flex; flex-wrap:wrap; gap:5px; }
    .sk-chips .sk { height:28px; border-radius:999px; }

    /* "Results ready" dot on the flower button. */
    .pill { position:relative; }
    .pill.ready::after { content:''; position:absolute; top:3px; right:3px; width:11px; height:11px; border-radius:50%;
      background:#4cc38a; box-shadow:0 0 0 2px var(--head); animation:pop .25s ease-out; }
    @keyframes pop { from { transform:scale(0); } }

    /* Calmer surfaces: fewer lines, more room between sections. */
    .body { padding:12px 16px 16px; }
    h3 { margin:20px 0 8px; }
    .hero { margin:-12px -16px 0; padding:16px 16px 14px; border-bottom:0; }
    .votes { border-top:0; margin-top:18px; gap:2px; }
    details.vline { border-bottom:0; border-radius:8px; padding:0 8px; margin:0 -8px; }
    details.vline:hover, details.vline[open] { background:var(--card); }
    details.others { margin-top:10px; border-radius:10px; background:var(--card); }
    details.others > summary { list-style:none; cursor:pointer; display:flex; align-items:center; gap:8px; padding:8px 10px; font-size:12px; }
    details.others > summary::-webkit-details-marker { display:none; }
    details.others > summary::after { content:'▾'; color:var(--muted); font-size:10px; transition:transform .15s; }
    details.others[open] > summary::after { transform:rotate(180deg); }
    details.others .ot { flex:1; min-width:0; color:var(--muted); }
    details.others .down { color:var(--accent); font-weight:700; font-variant-numeric:tabular-nums; }
    details.others > :not(summary) { margin-inline:10px; }
    details.others > :last-child { margin-bottom:10px; }
    details.others .perml { margin-top:2px; }
    .notepop { border:0; }
    .cand { border:0; }
    .top-info .photo { border:0; }
    .foot { margin-top:20px; }

    .foot { margin-top:20px; display:flex; justify-content:space-between; gap:8px; }
    .linkbtn.back { display:block; margin-top:10px; text-align:start; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:100%; }
    .linkbtn { background:none; border:0; color:var(--accent); font-size:12px; cursor:pointer; padding:0; }
    .msg { padding:6px 0; }
    .spin { width:18px; height:18px; border:2px solid var(--chip); border-top-color:var(--accent); border-radius:50%;
      animation:s .8s linear infinite; display:inline-block; vertical-align:middle; margin-right:8px; }
    @keyframes s { to { transform:rotate(360deg); } }
  `;

  const flower = size => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><g fill="#f58fb8">${[0, 72, 144, 216, 288].map(r => `<ellipse cx="12" cy="6.6" rx="3.9" ry="5.2" transform="rotate(${r} 12 12)"/>`).join('')}</g><circle cx="12" cy="12" r="3" fill="#ffd36e"/></svg>`;
  const gearIcon = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.6.77 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;

  const searchIcon = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`;

  // CSS variables for a theme.
  function themeCss(themeKey) {
    const t = { onAccent: '#ffffff', ...(FN.THEMES[themeKey] || FN.THEMES.plum) };
    return `:host { ${Object.entries(t).filter(([k]) => k !== 'name' && k !== 'dark').map(([k, v]) => `--${k}:${v};`).join(' ')} }`;
  }

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => (n >= 10000 ? (n / 1000).toFixed(0) + 'k' : n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n));
  const safeColor = (c, fallback) =>
    /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\))$/i.test(String(c || '').trim()) ? c.trim() : fallback;

  // Builds the results HTML. `opts.allowRemote` lets the settings preview use https images;
  // on shop pages only embedded (data:) images are used.
  function renderBody(d, S, opts = {}) {
    const on = S.sections;
    const simple = S.style === 'simple';   // same layout, but quieter: no emoji, note pictures or colour washes
    // Dark themes: tone Fragrantica's bright accord colours down by mixing them with the background.
    const isDark = !!(FN.THEMES[FN.resolveTheme ? FN.resolveTheme(S) : S.theme] || {}).dark;
    const accBg = c => { const v = safeColor(c, 'var(--soft)'); return isDark ? `color-mix(in oklab, ${v} 58%, var(--bg))` : v; };
    const accFg = c => isDark ? 'var(--fg)' : safeColor(c, 'var(--fg)');
    const L = d.labels || {};
    const T = key => L[key] || FN.t(S.lang, key);
    const okImg = src => S.style !== 'simple' && src &&
      (/^data:image\//.test(src) || (opts.allowRemote && /^https:\/\/fimgs\.net\//.test(src)));

    // Vote line: "Longevity ●●●●○ Long lasting". The dots show where the average vote sits on the scale
    // (for gender: one dot marks the position between female and male). Click to open all votes.
    const meanIndex = v => {
      const tot = v.rows.reduce((a, r) => a + r.n, 0) || 1;
      return v.rows.reduce((a, r, i) => a + i * r.n, 0) / tot;
    };
    const dots = (v, single) => {
      const n = v.rows.length, pos = Math.round(meanIndex(v));
      return `<span class="dots">${v.rows.map((r, i) => `<i class="${single ? (i === pos ? 'f' : '') : (i <= pos ? 'f' : '')}"></i>`).join('')}</span>`;
    };
    // Gender: a female ↔ male scale with a marker where the votes lean, instead of dots.
    const gscale = v => {
      const pos = v.rows.length > 1 ? meanIndex(v) / (v.rows.length - 1) * 100 : 50;
      return `<span class="gscale"><span class="gs">♀</span><span class="gtrack"><i style="left:${pos.toFixed(1)}%"></i></span><span class="gs">♂</span></span>`;
    };
    const voteBlock = (title, v, single = false) => {
      if (!v) return '';
      const max = Math.max(...v.rows.map(r => r.n), 1);
      return `<details class="vline"><summary><span class="vt">${title}</span>${single ? gscale(v) : dots(v)}<b>${esc(v.top)}</b></summary><div class="vote">${v.rows.map(r =>
        `<div class="vrow ${r.label === v.top ? 'top' : ''}" title="${r.n} votes"><span>${esc(r.label)}</span><span class="bar"><i style="width:${Math.max(3, Math.round(r.n / max * 100))}%"></i></span><em>${fmt(r.n)}</em></div>`
      ).join('')}</div></details>`;
    };
    // When to wear: seasons and day/night as two groups. Each bar shows its share of that group's votes;
    // the favourites are highlighted and named in a headline with icons, so the answer is clear at a glance.
    const WEAR_ICONS = simple ? ['', '', '', '', '', ''] : ['❄️', '🌸', '☀️', '🍂', '🌞', '🌙'];
    const wearBlock = w => {
      if (!w || !w.some(x => x.n)) return '';
      const groups = [w.slice(0, 4).map((x, i) => ({ ...x, icon: WEAR_ICONS[i] })), w.slice(4, 6).map((x, i) => ({ ...x, icon: WEAR_ICONS[4 + i] }))];
      const best = [];
      const cols = groups.map(g => {
        const sum = g.reduce((a, x) => a + x.n, 0) || 1, max = Math.max(...g.map(x => x.n), 1);
        g.filter(x => x.n >= max * 0.85).forEach(x => best.push(x));
        return g.map(x => {
          const share = Math.round(x.n / sum * 100), top = x.n >= max * 0.85;
          return `<div class="wc ${top ? 'hi' : ''}" title="${esc(x.label)}: ${x.n.toLocaleString()} votes (${share}%)"><span class="wp">${share}%</span><div class="track"><div class="fill" style="height:${Math.max(6, Math.round(x.n / max * 100))}%"></div></div>${x.icon ? `<span class="wi">${x.icon}</span>` : ''}<span class="wl">${esc(x.label)}</span></div>`;
        }).join('');
      });
      const head = best.map(x => `<span class="wb">${x.icon ? x.icon + ' ' : ''}<span>${esc(x.label)}</span></span>`).join('');
      return `<h3>${esc(T('wear'))}</h3><div class="wbest">${head}</div><div class="wear">${cols[0]}<span class="wsep"></span>${cols[1]}</div>`;
    };

    // Pros & cons summarised by Fragrantica from reviews; the agree % is from votes on each point.
    const prosConsBlock = pc => {
      if (!pc) return '';
      const L = d.labels || {};
      const item = (o, cls) => {
        const tot = o.yes + o.no, pct = tot ? Math.round(o.yes / tot * 100) : 0;
        return `<li class="${cls}" title="${o.yes.toLocaleString()} 👍 · ${o.no.toLocaleString()} 👎"><span class="pi"><svg viewBox="0 0 10 10" width="8" height="8" aria-hidden="true"><path d="${cls === 'pro' ? 'M5 1v8M1 5h8' : 'M1 5h8'}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></span><span class="pt">${esc(o.text)}</span>${tot ? `<em>${pct}%</em>` : ''}</li>`;
      };
      const col = (list, cls, title) => list.length ? `<div class="pcol"><b>${esc(title)}</b><ul>${list.map(o => item(o, cls)).join('')}</ul></div>` : '';
      return `<h3>${esc(L.prosCons || FN.t(S.lang, 'prosCons'))}</h3><div class="pc">${col(pc.pros, 'pro', L.pros || FN.t(S.lang, 'pros'))}${col(pc.cons, 'con', L.cons || FN.t(S.lang, 'cons'))}</div>`;
    };

    const noteChip = n => {
      const name = typeof n === 'string' ? n : n.name;
      const img = typeof n === 'string' ? '' : n.img;
      const url = typeof n === 'string' ? '' : n.url || '';
      const attrs = url ? ` data-note="${esc(url)}" data-name="${esc(name)}" data-img="${esc(okImg(img) ? img : '')}" role="button" tabindex="0"` : '';
      return okImg(img)
        ? `<span class="chip${url ? ' nb' : ''}"${attrs}><img src="${esc(img)}" alt="">${esc(name)}</span>`
        : `<span class="chip noimg${url ? ' nb' : ''}"${attrs}>${esc(name)}</span>`;
    };
    const votes = [
      on.longevity && voteBlock(esc(T('longevity')), d.longevity),
      on.sillage && voteBlock(esc(T('sillage')), d.sillage),
      on.priceValue && voteBlock(esc(T('priceValue')), d.priceValue),
      on.gender && voteBlock(esc(T('gender')), d.gender, true)
    ].filter(Boolean).join('');
    const photo = on.photo && d.photo && (/^data:image\//.test(d.photo) || (opts.allowRemote && /^https:\/\/fimgs\.net\//.test(d.photo)))
      ? `<img class="photo" src="${esc(d.photo)}" alt="">` : '';
    const maxAcc = Math.max(...(d.accords || []).map(a => a.width), 1);
    // badge = show a "dupe" tag (only in the general list; the dupes section's title already says it)
    const simCard = (s, badge = true) => `<a class="simc" href="${esc(s.url)}" target="_blank" title="${esc((s.brand ? s.brand + ' – ' : '') + s.name)}">${okImg(s.img) ? `<img src="${esc(s.img)}" alt="">` : ''}<span class="t"><span class="n">${esc(s.name)}</span>${s.brand || s.dupe ? `<span class="b"><span class="bn">${esc(s.brand || '')}</span>${badge && s.dupe && on.dupes ? `<span class="badge">${esc(FN.t(S.lang, 'dupe'))}</span>` : ''}</span>` : ''}</span></a>`;

    // Price per ml, from the sizes and prices on the shop page.
    const prices = opts.prices || [];
    const bestPer = prices.length ? Math.min(...prices.map(x => x.price / x.ml)) : 0;
    const money = (n, cur) => { try { return new Intl.NumberFormat(S.lang, { style: 'currency', currency: cur || 'EUR' }).format(n); } catch { return (cur || '') + ' ' + n.toFixed(2); } };
    const perMl = on.perMl && prices.length ? `<div class="perml">${prices.map(x => {
      const per = x.price / x.ml, best = prices.length > 1 && Math.abs(per - bestPer) < 1e-9;
      return `<span class="ml">${esc(String(x.ml))} ml</span><span>${esc(money(x.price, x.currency))}</span><span class="pp ${best ? 'best' : ''}">${best ? `<span class="badge">${esc(FN.t(S.lang, 'best'))}</span>` : ''}${esc(money(per, x.currency))}/ml</span>`;
    }).join('')}</div>` : '';

    // Price per ml at other shops the user looked at this perfume (saved locally while browsing).
    // Other shops: prices you saw yourself on other shops (opts.elsewhere),
    // merged into one list — one line per shop (its cheapest per ml), cheapest first.
    const herePer = prices.length ? bestPer : Infinity;
    const hereCur = prices[0]?.currency;
    let ago = () => '';
    try {
      const rtf = new Intl.RelativeTimeFormat(S.lang, { numeric: 'auto' });
      ago = t => { const d = Math.round((t - Date.now()) / 864e5); return Math.abs(d) < 30 ? rtf.format(d, 'day') : rtf.format(Math.round(d / 30), 'month'); };
    } catch {}
    const shopKey = s => String(s || '').toLowerCase().replace(/^www\./, '').replace(/\.(co\.uk|com\.au|[a-z]{2,3})$/, '')
      .replace(/\s(nl|be|de|fr|uk|es|it|com)$/, '').replace(/^(de|the|la|le)\s+/, '').replace(/[^a-z0-9]/g, '');
    // One line per shop (its cheapest per ml), cheapest first; the shop you're on is left out.
    const best = new Map();
    for (const o of opts.elsewhere || []) {
      const r = { shop: o.host, ml: o.ml, price: o.per * (o.ml || 1), per: o.per, currency: o.currency, url: o.url, note: ago(o.t) };
      const k = shopKey(r.shop);
      if (!(r.per > 0) || k === shopKey(opts.host)) continue;
      if (!best.has(k) || r.per < best.get(k).per) best.set(k, r);
    }
    const list = [...best.values()].sort((x, y) => x.per - y.per);
    const shown = opts.othersAll ? list : list.slice(0, 5);
    const elsewhere = list.length ? `<div class="perml others">${shown.map(r => {
      const cheaper = r.currency === hereCur && r.per < herePer - 1e-9;
      return `<a class="ml" href="${esc(r.url)}" target="_blank" title="${esc(r.shop + (r.note ? ' · ' + r.note : ''))}">${esc(r.shop)}</a><span class="sz">${r.ml ? esc(String(r.ml)) + ' ml' : ''}</span><span class="pr">${r.ml ? esc(money(r.price, r.currency)) : ''}</span><span class="pp ${cheaper ? 'best' : ''}">${esc(money(r.per, r.currency))}/ml</span>`;
    }).join('')}</div>${list.length > shown.length ? `<button class="more" type="button">+${list.length - shown.length}</button>` : ''}` : '';

    // Prices: this shop's sizes are shown; other shops sit in a fold-out underneath.
    const cheapest = list[0];
    const cheaperElsewhere = cheapest && (!prices.length || (cheapest.currency === hereCur && cheapest.per < herePer - 1e-9));
    const othersFold = on.elsewhere && list.length ? `<details class="others"${opts.pricesOpen ? ' open' : ''}><summary><span class="ot">${esc(FN.t(S.lang, 'elsewhere'))}</span>${
      cheaperElsewhere ? `<span class="down">${prices.length ? '↓ ' : ''}${esc(money(cheapest.per, cheapest.currency))}/ml</span>` : ''}</summary>${elsewhere}</details>` : '';
    const pricesBlock = perMl || othersFold ? `<h3>${esc(FN.t(S.lang, 'perMl'))}</h3>${perMl}${othersFold}` : '';

    // 4. Header tinted with the perfume's top accord colours.
    const tint = (c, a) => {
      const m = String(c || '').match(/rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/);
      if (m) return `rgba(${m[1]}, ${m[2]}, ${m[3]}, ${a})`;
      const h = String(c || '').match(/^#([0-9a-f]{6})$/i);
      return h ? `rgba(${parseInt(h[1].slice(0, 2), 16)}, ${parseInt(h[1].slice(2, 4), 16)}, ${parseInt(h[1].slice(4, 6), 16)}, ${a})` : '';
    };
    const dark = isDark;
    const accCols = (d.accords || []).slice(0, 3).map(a => tint(a.bg, dark ? 0.24 : 0.28)).filter(Boolean);
    const heroBg = S.style !== 'simple' && accCols.length
      ? `background:linear-gradient(120deg, ${accCols.join(', ')}${accCols.length === 1 ? ', transparent' : ''});` : '';

    // 1. Summary strip: rating, longevity, sillage and when to wear.
    const wearBest = (() => {
      const w = d.wear || [];
      if (!w.some(x => x.n)) return null;
      const pick = g => { const max = Math.max(...g.map(x => x.n), 1); return g.filter(x => x.n >= max * 0.85); };
      const seasons = pick(w.slice(0, 4).map((x, i) => ({ ...x, icon: WEAR_ICONS[i] })));
      const time = pick(w.slice(4, 6).map((x, i) => ({ ...x, icon: WEAR_ICONS[4 + i] })));
      return { icons: [...seasons, ...time].map(x => x.icon).join(''), text: [...seasons, ...time].map(x => x.label).join(' · ') };
    })();
    const tile = (value, caption, title = '') => `<div class="tile" title="${esc(title || value)}"><b>${value}</b><span>${esc(caption)}</span></div>`;
    const summary = on.summary !== false ? [
      d.rating && tile(`★ ${esc(d.rating)}`, `${T('rating')} · ${fmt(+d.ratingCount || 0)}`),
      d.longevity && tile(esc(d.longevity.top), T('longevity')),
      d.sillage && tile(esc(d.sillage.top), T('sillage')),
      wearBest && (simple ? tile(esc(wearBest.text), T('wear')) : tile(`<span class="ic">${wearBest.icons}</span>`, T('wear'), wearBest.text))
    ].filter(Boolean).join('') : '';

    // 3. Accords: bars (default) or one colour strip with labelled chips underneath.
    const accHtml = !(on.accords && d.accords?.length) ? '' : S.accStyle === 'strip'
      ? `<h3>${esc(T('accords'))}</h3><div class="astrip">${d.accords.map(a =>
          `<i title="${esc(a.name)} · ${Math.round(a.width)}%" style="flex-grow:${Math.max(4, a.width)};background:${accBg(a.bg)}"></i>`).join('')}</div>
        <div class="achips">${d.accords.map(a => `<span class="achip"><i style="background:${accBg(a.bg)}"></i>${esc(a.name)}</span>`).join('')}</div>`
      : `<h3>${esc(T('accords'))}</h3><div class="accs">${d.accords.map(a =>
          `<div class="accbar" title="${esc(a.name)} · ${Math.round(a.width)}%" style="width:${Math.max(30, Math.round(a.width / maxAcc * 100))}%;background:${accBg(a.bg)};color:${accFg(a.fg)}">${esc(a.name)}</div>`).join('')}</div>`;

    // 5. Notes as a pyramid: tier name in a narrow column on the left, notes on the right.
    const multi = (d.notes || []).length > 1;
    const notesHtml = !on.notes ? '' : `<h3>${esc(FN.t(S.lang, 'notes'))}</h3>${d.notes?.length
      ? `<div class="pyr${multi ? '' : ' flat'}">${d.notes.map((t, i) =>
          `<div class="tier lv${i}">${multi && t.label ? `<div class="tl"><span>${esc(t.label)}</span></div>` : ''}<div class="chips">${t.names.map(noteChip).join('')}</div></div>`).join('')}</div>`
      : `<div class="muted">${esc(FN.t(S.lang, 'noNotes'))}</div>`}`;

    return `
      <div class="hero" style="${heroBg}">
        <div class="top-info">
          ${photo}
          <div class="ti">
            <h2><a href="${esc(d.url)}" target="_blank">${esc(d.title || opts.query || '')}</a></h2>
            ${on.meta ? `<div class="meta">${[
              d.year && esc(d.year),
              d.audience && esc(d.audience),
              !summary && d.rating && `★ ${esc(d.rating)} (${fmt(+d.ratingCount || 0)})`
            ].filter(Boolean).join('<span>·</span>')}</div>` : ''}
          </div>
        </div>
        ${summary ? `<div class="tiles">${summary}</div>` : ''}
      </div>

      ${accHtml}

      ${notesHtml}

      ${on.wear ? wearBlock(d.wear) : ''}
      ${on.prosCons !== false ? prosConsBlock(d.prosCons) : ''}

      ${votes ? `<div class="votes">${votes}</div>` : ''}

      ${pricesBlock}

      ${on.similar && d.similar?.length ? `<h3>${esc(T('similar'))}</h3><div class="sims row3">${d.similar.slice(0, 3).map(s => simCard(s)).join('')}</div>` : ''}

      ${on.dupes && d.dupes?.length ? `<h3>${esc(FN.t(S.lang, 'dupes'))}</h3><div class="sims row3 dupes">${d.dupes.slice(0, 3).map(s => simCard(s, false)).join('')}</div>` : ''}

      <div class="foot">
        <span class="muted">${esc(FN.t(S.lang, 'data'))} · ${esc(FN.t(S.lang, 'notAffiliated'))}${opts.cached ? ' · ' + esc(FN.t(S.lang, 'cached')) : ''}</span>
        ${opts.noRefresh ? '' : `<button class="linkbtn refresh">${esc(FN.t(S.lang, 'refresh'))}</button>`}
      </div>`;
  }

  // Panel markup (header, search form, body). Used in-page and in the preview.
  const panelHtml = `
    <div class="rz"></div>
    <div class="head">${flower(16)}<span class="t">Fragrance notes</span><button class="srch" type="button" title="Search">${searchIcon}</button><button class="gear" title="Settings">${gearIcon}</button></div>
    <form><input name="q" placeholder="Brand + perfume, or a Fragrantica URL"><button>Search</button></form>
    <div class="body"></div>`;

  // Translate the panel's fixed text (title, search box) for the chosen language.
  function localizeChrome(root, lang) {
    const set = (sel, fn) => { const el = root.querySelector(sel); if (el) fn(el); };
    set('.panel', el => { el.lang = lang; el.dir = ['ar', 'he'].includes(lang) ? 'rtl' : 'ltr'; });
    set('.head .t', el => { el.textContent = FN.t(lang, 'title'); });
    set('form input', el => { el.placeholder = FN.t(lang, 'placeholder'); });
    set('form button', el => { el.textContent = FN.t(lang, 'search'); });
    set('.srch', el => { el.title = FN.t(lang, 'search'); });
  }

  globalThis.FN_UI = { localizeChrome, CSS, flower, gearIcon, themeCss, renderBody, panelHtml, esc };
})();
