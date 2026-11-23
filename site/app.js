/* Timebase Witness - live view of an MQTT broker's namespace and an OPC UA server's address space.
   Plain JavaScript, no build step. Every connection (MQTT and OPC UA) is owned by the Witness gateway,
   which streams data over /api/stream/ws and is managed through /api/connections.
   OPC UA arrives through the Witness gateway (gateway/gateway.py) at /api/opcua/ws.
   The shell (sidebar, tab strip, page header, lists) mirrors the Timebase 2.0 apps. */
(() => {
  'use strict';

  // ---------------------------------------------------------------- helpers
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // Lucide icons (the Timebase apps use lucide-react)
  const ICON = {
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    network: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
    cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    plug: '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
    server: '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
    radio: '<path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"/>',
    maximize: '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" x2="14" y1="3" y2="10"/><line x1="3" x2="10" y1="21" y2="14"/>',
    minimize: '<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" x2="21" y1="10" y2="3"/><line x1="3" x2="10" y1="21" y2="14"/>',
    expand: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
    pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    brain: '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>',
    collapse: '<path d="m7 20 5-5 5 5"/><path d="m7 4 5 5 5-5"/>',
  };
  const icon = (n, cls = 'ic') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  };
  const ENVELOPE = new Set(['instanceUri', 'anchor', 'emitTime', 'watermark']);

  const humanize = (k) => String(k).replace(/[_-]+/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
  const pick = (o, name) => { if (!o) return undefined; const k = Object.keys(o).find((x) => x.toLowerCase() === name); return k === undefined ? undefined : o[k]; };
  const has = (o, name) => Object.keys(o).some((x) => x.toLowerCase() === name);
  const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const isTVQ = (v) => isObj(v) && has(v, 'value') && (has(v, 'quality') || has(v, 'timestamp'));
  const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

  function fmtNum(v) {
    if (!Number.isFinite(v)) return String(v);
    const a = Math.abs(v);
    const d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : a === 0 ? 0 : 3;
    return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: d });
  }
  function fmtTime(ms, withMs) {
    const d = new Date(ms);
    const s = d.toLocaleTimeString([], { hour12: false });
    return withMs ? `${s}.${String(d.getMilliseconds()).padStart(3, '0')}` : s;
  }
  function fmtVal(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number') return fmtNum(v);
    if (typeof v === 'boolean') return v ? 'True' : 'False';
    if (typeof v === 'string' && ISO.test(v)) { const t = Date.parse(v); if (!isNaN(t)) return new Date(t).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }); }
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }
  function ago(ts) {
    if (!ts) return '—';
    const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (s < 2) return 'just now';
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ${m % 60}m ago`;
    return `${Math.floor(h / 24)}d ago`;
  }
  function duration(sec) {
    if (!Number.isFinite(sec)) return '—';
    const d = Math.floor(sec / 86400); const h = Math.floor((sec % 86400) / 3600); const m = Math.floor((sec % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${Math.floor(sec % 60)}s`;
  }
  function bytes(n) {
    if (!Number.isFinite(n)) return '—';
    const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
  }
  function quality(q) {
    if (q === undefined || q === null) return null;
    if (typeof q === 'string') {
      const s = q.toLowerCase();
      if (s.startsWith('good')) return { cls: 'good', label: 'Good' };
      if (s.startsWith('uncertain')) return { cls: 'unc', label: 'Uncertain' };
      if (s.startsWith('bad')) return { cls: 'bad', label: 'Bad' };
      const n = Number(q); if (!isNaN(n)) q = n; else return { cls: 'unc', label: q };
    }
    if (q >= 192) return { cls: 'good', label: 'Good' };
    if (q >= 64) return { cls: 'unc', label: 'Uncertain' };
    return { cls: 'bad', label: 'Bad' };
  }
  function merge(a, b) {
    if (!isObj(a) || !isObj(b)) return b;
    const out = { ...a };
    for (const k of Object.keys(b)) out[k] = isObj(a[k]) && isObj(b[k]) && !isTVQ(b[k]) ? merge(a[k], b[k]) : b[k];
    return out;
  }
  // JSON path of a key below p: a.b, a[0], a["odd key"]; jsonPath() adds the $ for JSONPath
  const pk = (p, k) => (/^[A-Za-z_][\w]*$/.test(k) ? (p ? `${p}.${k}` : k) : `${p}[${JSON.stringify(k)}]`);
  const jsonPath = (p) => (!p ? '$' : p[0] === '[' ? `$${p}` : `$.${p}`);
  function getAt(v, path) {
    if (!path) return v;
    let hit; let found = false;
    const walk = (x, p) => {
      if (found) return;
      if (p === path) { hit = x; found = true; return; }
      if (p && !path.startsWith(p)) return;
      if (Array.isArray(x)) x.forEach((y, i) => walk(y, `${p}[${i}]`));
      else if (x && typeof x === 'object') for (const k of Object.keys(x)) walk(x[k], pk(p, k));
    };
    walk(v, '');
    return found ? hit : undefined;
  }
  function leaves(v, p, out) {
    if (isObj(v)) { for (const k of Object.keys(v)) leaves(v[k], pk(p, k), out); }
    else if (Array.isArray(v)) v.forEach((x, i) => leaves(x, `${p}[${i}]`, out));
    else out.set(p, v);
    return out;
  }
  function changedPaths(prev, cur) {
    const set = new Set();
    if (prev === undefined) return set;
    const a = leaves(prev, '', new Map()); const b = leaves(cur, '', new Map());
    for (const [k, v] of b) if (!a.has(k) || a.get(k) !== v) set.add(k);
    return set;
  }
  function jsonHtml(v, p, ch, ind) {
    const pad = '  '.repeat(ind);
    if (v === null) return `<span class="j-null${ch.has(p) ? ' chg' : ''}" data-act="jval" data-jp="${esc(p)}" title="Copy value">null</span>`;
    if (Array.isArray(v)) {
      if (!v.length) return '[]';
      return `[\n${v.map((x, i) => `${pad}  ${jsonHtml(x, `${p}[${i}]`, ch, ind + 1)}`).join(',\n')}\n${pad}]`;
    }
    if (typeof v === 'object') {
      const ks = Object.keys(v);
      if (!ks.length) return '{}';
      return `{\n${ks.map((k) => { const q = pk(p, k); return `${pad}  <span class="j-key" data-act="jkey" data-jp="${esc(q)}" title="${esc(jsonPath(q))} - click for copy options">"${esc(k)}"</span>: ${jsonHtml(v[k], q, ch, ind + 1)}`; }).join(',\n')}\n${pad}}`;
    }
    const cls = typeof v === 'string' ? 'j-str' : typeof v === 'number' ? 'j-num' : 'j-bool';
    const s = typeof v === 'string' ? `"${esc(v)}"` : esc(String(v));
    return `<span class="${cls}${ch.has(p) ? ' chg' : ''}" data-act="jval" data-jp="${esc(p)}" title="Copy value">${s}</span>`;
  }
  function oneLine(text, max = 180) {
    const t = String(text).replace(/\s+/g, ' ');
    return t.length > max ? `${t.slice(0, max)}…` : t;
  }
  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t).catch(() => legacyCopy(t));
    legacyCopy(t); return Promise.resolve();
  }
  function legacyCopy(t) {
    const ta = document.createElement('textarea');
    ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch { /* ignore */ }
    ta.remove();
  }
  let toastTimer = 0;
  function toast(msg) {
    let el = document.getElementById('toast');
    if (!el) { el = document.createElement('div'); el.id = 'toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
    el.innerHTML = `${icon('check', 'ic-sm')}<span>${esc(msg)}</span>`;
    el.classList.add('on');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('on'), 1600);
  }
  function copied(text, what) { return copyText(text).then(() => toast(`Copied ${what}`)); }
  const valText = (v) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2));
  const csvCell = (v) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const shq = (v) => `'${String(v).replace(/'/g, `'\\''`)}'`;

  // Copy menu: one floating list on <body>, so live re-renders of the detail pane do not close it.
  // Items are { label, hint?, text: () => string, what }; separators are null.
  let MENU = null;
  function openMenu(anchor, items) {
    closeMenu();
    const el = document.createElement('div');
    el.id = 'cmenu'; el.className = 'cmenu'; el.setAttribute('role', 'menu');
    el.innerHTML = items.map((it, i) => (it ? `<button role="menuitem" data-act="mitem" data-i="${i}"><span>${esc(it.label)}</span>${it.hint ? `<small>${esc(it.hint)}</small>` : ''}</button>` : '<div class="cmenu-sep"></div>')).join('');
    document.body.appendChild(el);
    const r = anchor.getBoundingClientRect();
    const w = el.offsetWidth; const h = el.offsetHeight;
    const left = Math.max(8, Math.min(anchor.tagName === 'BUTTON' ? r.right - w : r.left, window.innerWidth - w - 8));
    const top = r.bottom + 4 + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 4) : r.bottom + 4;
    el.style.left = `${left}px`; el.style.top = `${top}px`;
    MENU = { el, items, anchor };
  }
  function closeMenu() { if (MENU) { MENU.el.remove(); MENU = null; } }
  // the payload being shown in the detail pane: the selected topic's own message, or its retained state
  function shownPayload() {
    const c = cur(); const n = find(c, c.selected);
    if (!n) return null;
    if (n.raw !== null) return n;
    const st = n.hasState ? n.children.get('state') : null;
    return st && st.raw !== null ? st : null;
  }
  function msgJson(src, h) {
    const ua = !!src.ua;
    const o = ua ? { nodeId: src.ua.id, browsePath: localPath(src) } : { topic: localPath(src) };
    let payload = h.raw;
    try { payload = JSON.parse(h.raw); } catch { /* text */ }
    o[ua ? 'dataValue' : 'payload'] = payload;
    if (!ua) { o.retained = !!h.retained; if (h === src.history[0]) o.qos = src.qos; }
    o.receivedAt = new Date(h.t).toISOString();
    return JSON.stringify(o, null, 2);
  }
  function pubCommand(src) {
    const b = BROKERS.find((x) => x.name === topOf(src).name);
    let host = 'localhost'; let port = '1883'; let tls = false;
    try { const u = new URL(b.url); host = u.hostname; port = u.port || (u.protocol === 'mqtts:' ? '8883' : '1883'); tls = u.protocol === 'mqtts:'; } catch { /* keep defaults */ }
    const auth = b && b.username ? ` -u ${shq(b.username)} -P '<password>'` : '';
    return `mosquitto_pub -h ${host} -p ${port}${tls ? ' --cafile <ca.pem>' : ''}${auth} -t ${shq(localPath(src))} -q ${src.qos || 0}${src.retained ? ' -r' : ''} -m ${shq(src.raw)}`;
  }
  function historyLines(src) { return src.history.map((h) => msgJson(src, h).replace(/\n\s*/g, ' ')).join('\n'); }
  function historyCsv(src) {
    const ua = !!src.ua;
    const head = ua ? 'received_at,payload' : 'received_at,retained,payload';
    return [head, ...src.history.map((h) => [new Date(h.t).toISOString(), ...(ua ? [] : [h.retained ? 'true' : 'false']), csvCell(h.raw)].join(','))].join('\n');
  }
  function flatPaths(json) {
    return [...leaves(json, '', new Map())].map(([k, v]) => `${jsonPath(k)}\t${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n');
  }
  function payloadMenu(src) {
    const ua = !!src.ua; const isJson = src.json !== undefined;
    const items = [
      { label: ua ? 'Data value' : 'Payload', hint: 'as received', text: () => src.raw, what: ua ? 'data value' : 'payload' },
    ];
    if (isJson) {
      items.push({ label: 'Formatted JSON', hint: 'indented', text: () => JSON.stringify(src.json, null, 2), what: 'formatted JSON' });
      items.push({ label: 'Compact JSON', hint: 'one line', text: () => JSON.stringify(src.json), what: 'compact JSON' });
      items.push({ label: 'Paths and values', hint: 'JSONPath, tab, value', text: () => flatPaths(src.json), what: 'paths and values' });
    }
    if (ua && isJson && src.json && typeof src.json === 'object' && 'value' in src.json) items.push({ label: 'Value only', text: () => valText(src.json.value), what: 'value' });
    items.push(null);
    items.push(ua ? { label: 'NodeId', text: () => src.ua.id, what: 'NodeId' } : { label: 'Topic', text: () => localPath(src), what: 'topic' });
    items.push({ label: ua ? 'Node and value as JSON' : 'Topic and message as JSON', hint: 'with time', text: () => msgJson(src, src.history[0] || { t: src.last, raw: src.raw, retained: src.retained }), what: 'message' });
    if (!ua) items.push({ label: 'mosquitto_pub command', hint: 'replays this message', text: () => pubCommand(src), what: 'mosquitto_pub command' });
    if (src.history.length) {
      items.push(null);
      items.push({ label: `History as JSON lines`, hint: `${src.history.length} ${ua ? "update" : "message"}${src.history.length === 1 ? "" : "s"}`, text: () => historyLines(src), what: 'history' });
      items.push({ label: `History as CSV`, hint: `${src.history.length} ${ua ? "update" : "message"}${src.history.length === 1 ? "" : "s"}`, text: () => historyCsv(src), what: 'history as CSV' });
    }
    return items;
  }
  function keyMenu(src, path) {
    const key = (path.match(/(?:\.|^)([A-Za-z_]\w*)$|\["((?:[^"\\]|\\.)*)"\]$|\[(\d+)\]$/) || []).slice(1).find((x) => x !== undefined) || path;
    return [
      { label: 'Value', text: () => valText(getAt(src.json, path)), what: 'value' },
      { label: 'JSONPath', hint: jsonPath(path), text: () => jsonPath(path), what: 'JSONPath' },
      { label: 'Dotted path', hint: path, text: () => path, what: 'path' },
      { label: 'Key name', hint: key, text: () => key, what: 'key' },
      null,
      { label: 'Path and value', text: () => `${jsonPath(path)} = ${JSON.stringify(getAt(src.json, path))}`, what: 'path and value' },
    ];
  }

  // ---------------------------------------------------------------- state
  const VIEWS = {
    conn: { label: 'Connections', title: 'Connections', icon: 'plug' },
    atlas: { label: 'Handoffs', title: 'Handoffs', icon: 'sparkles' },
  };
  const HIST = 300; // 5 minutes of 1 s samples for the Connections tiles
  function mkNode(name, path, parent) {
    return { name, path, parent, children: new Map(), raw: null, json: undefined, prevJson: undefined,
      retained: false, qos: 0, count: 0, sub: 0, last: 0, activity: 0, topics: 0, hasPayload: false,
      history: [], view: null, series: new Map(), selProp: null, hasState: false, ua: null, conn: null };
  }
  function mkCtx(key) {
    return { key, root: mkNode('', '', null), selected: '', expanded: new Set(), collapsed: new Set(), filter: '', showSys: false,
      treeDirty: true, viewDirty: true, viewKey: null, tab: 'latest', count: 0, tick: 0, rateHist: [], total: 0 };
  }
  const CTX = { mqtt: mkCtx('mqtt'), ua: mkCtx('ua') };
  const S = {
    view: 'conn', tabs: ['conn'], paused: false, feedSeen: 0, feedId: 0,
    lens: new Map(),             // per connection tab: { local, filter, showSys, tab, live, bound }
    pendingLegacy: null,         // old #/ns/... or #/ua/... link, resolved once connections arrive
    connsLoaded: false,
    openConn: new Set(), connFilter: '', uaSocket: 'connecting',
    agent: { server: null, domain: '', running: false, items: [], brief: '', draft: '', error: null, info: null, usage: null, dirty: true, es: null, artifact: null, versions: [], collector: '', handoff: 'atlas' },
  };
  let apiBase = '';
  const BROKERS = [];          // MQTT connections from config.json
  const SERVERS = new Map();   // OPC UA servers reported by the gateway, by id
  // A connection opens in its own tab, view id "c:<connection id>". It browses that connection's
  // branch of the shared MQTT or OPC UA tree; selection, filter and the Live messages window are per tab.
  const isConnView = (v) => typeof v === 'string' && v.startsWith('c:');
  function connOf(v) {
    if (!isConnView(v)) return null;
    const id = v.slice(2);
    const b = BROKERS.find((x) => x.id === id);
    if (b) return { kind: 'mqtt', id, name: b.name, b };
    const sv = SERVERS.get(id);
    return sv ? { kind: 'ua', id, name: sv.name, s: sv } : null;
  }
  function vinfo(v) {
    if (VIEWS[v]) return VIEWS[v];
    if (!isConnView(v)) return null;
    const k = connOf(v);
    if (!k && S.connsLoaded) return null;
    return { label: k ? k.name : 'Connecting…', title: k ? k.name : 'Connecting…', icon: k && k.kind === 'ua' ? 'cpu' : 'network', ctx: k && k.kind === 'ua' ? 'ua' : 'mqtt', conn: k };
  }
  function lensOf(v) {
    let l = S.lens.get(v);
    if (!l) { l = { local: '', filter: '', showSys: false, tab: 'latest', live: false, wide: false, bound: false }; S.lens.set(v, l); }
    return l;
  }
  const ctxOf = (view) => CTX[(vinfo(view) && vinfo(view).ctx) || 'mqtt'];
  const cur = () => ctxOf(S.view);
  const isSys = (path) => path.split('/')[1] === '$SYS';
  const pushHist = (arr, v) => { arr.push(v); if (arr.length > HIST) arr.shift(); };

  function find(c, path) {
    if (!path) return c.root;
    let n = c.root;
    for (const p of path.split('/')) { n = n.children.get(p); if (!n) return null; }
    return n;
  }
  function ensure(c, path, autoDepth = 3) {
    let n = c.root; const parts = path.split('/');
    parts.forEach((p, i) => {
      let k = n.children.get(p);
      if (!k) {
        k = mkNode(p, parts.slice(0, i + 1).join('/'), n);
        n.children.set(p, k);
        if (i <= autoDepth && !isSys(path) && !c.collapsed.has(n.path)) c.expanded.add(n.path);
        if (c.selected.startsWith(`${k.path}/`)) c.expanded.add(k.path);
        c.treeDirty = true;
      }
      n = k;
    });
    return n;
  }
  function topOf(n) { while (n.parent && n.parent.parent) n = n.parent; return n; }
  const localPath = (n) => n.path.slice(topOf(n).name.length + 1);
  // topic count without the broker's own $SYS topics
  const visTopics = (n) => { const sys = n.children.get('$SYS'); return n.topics - (sys && n.conn ? sys.topics : 0); };
  function markPayload(c, n) {
    if (n.hasPayload) return;
    n.hasPayload = true; c.treeDirty = true;
    for (let a = n; a; a = a.parent) a.topics++;
    if (!isSys(n.path)) c.count++;
  }
  function touch(c, n, now) {
    for (let a = n; a; a = a.parent) { a.sub++; a.activity = now; }
    c.total++;
    c.treeDirty = true;
    const sel = c.selected;
    if (n.path === sel || n.path.startsWith(sel ? `${sel}/` : '') || (n.parent && n.parent.path === sel)) c.viewDirty = true;
  }
  function push(n, key, t, v) {
    let arr = n.series.get(key);
    if (!arr) { arr = []; n.series.set(key, arr); }
    const last = arr[arr.length - 1];
    if (last && last.t === t) { last.v = v; return; }
    arr.push({ t, v });
    if (arr.length > 1 && t < arr[arr.length - 2].t) arr.sort((x, y) => x.t - y.t);
    if (arr.length > 720) arr.shift();
  }
  function record(n, obj, now) {
    for (const k of Object.keys(obj)) {
      const v = obj[k];
      if (isTVQ(v)) {
        let val = pick(v, 'value');
        if (typeof val === 'boolean') val = val ? 1 : 0;
        if (typeof val === 'number') push(n, k, Date.parse(pick(v, 'timestamp')) || now, val);
      } else if (typeof v === 'number' && !ENVELOPE.has(k)) push(n, k, now, v);
    }
  }
  // each connection keeps its own 300 most recent messages, so a busy server cannot push a quiet one out
  const FEED = new Map();
  function feedPush(connId, src, topic, text) {
    let list = FEED.get(connId);
    if (!list) { list = []; FEED.set(connId, list); }
    list.unshift({ t: Date.now(), src, topic, text, id: ++S.feedId });
    if (list.length > 300) list.pop();
  }
  const feedItems = (connId) => FEED.get(connId) || [];

  // ---------------------------------------------------------------- MQTT (one client per broker)
  function onMqtt(b, e, snapshot) {
    const c = CTX.mqtt; const now = Date.now();
    const topic = e.t;
    const full = `${b.name}/${topic}`;
    const n = ensure(c, full);
    const text = e.b ? `(binary payload, ${Math.floor((e.p.length * 3) / 4)} bytes, base64) ${e.p}` : e.p;
    if (text !== '') markPayload(c, n);
    n.raw = text; n.retained = !!e.r; n.qos = e.q; n.count++; n.last = now;
    let json;
    const tt = text.trim();
    if (tt && (tt[0] === '{' || tt[0] === '[')) { try { json = JSON.parse(tt); } catch { json = undefined; } }
    n.prevJson = n.json; n.json = json;
    n.history.unshift({ t: now, raw: text, retained: n.retained });
    if (n.history.length > 60) n.history.pop();
    if (isObj(json)) {
      n.view = merge(n.view || {}, json);
      record(n, json, now);
      if (n.name === 'state' && n.parent && n.parent.parent !== c.root && n.parent !== c.root) {
        const p = n.parent;
        p.view = merge(p.view || {}, json); p.hasState = true; record(p, json, now);
      }
    } else if (tt !== '' && json === undefined && Number.isFinite(Number(tt))) {
      push(n, '', now, Number(tt));
    }
    touch(c, n, now);
    b.total++;
    if (topic.startsWith('$SYS/')) b.sys[topic.slice(5)] = tt;
    else if (!snapshot) { c.tick++; b.tick++; feedPush(b.id, 'mqtt', full, text); }
  }
  function newHist() { return { rate: [], recv: [], sent: [], clients: [], retained: [], bytesIn: [] }; }
  function dropBranch(c, name) {
    const old = c.root.children.get(name); if (!old) return;
    const sys = old.children.get('$SYS');
    c.root.topics -= old.topics;
    c.count -= old.topics - (sys ? sys.topics : 0);
    c.root.children.delete(name);
    if (c.selected === name || c.selected.startsWith(`${name}/`)) c.selected = '';
    c.treeDirty = true; c.viewDirty = true;
  }
  function brokerFor(st) {
    let b = BROKERS.find((x) => x.id === st.id);
    if (!b) { b = { id: st.id, name: st.name, sys: {}, total: 0, tick: 0, hist: newHist() }; BROKERS.push(b); }
    if (b.name !== st.name) { dropBranch(CTX.mqtt, b.name); b.sys = {}; b.name = st.name; }
    b.status = st; b.url = st.endpoint; b.username = st.user; b.error = st.error;
    b.conn = st.enabled === false ? 'disabled' : st.state;
    b.since = st.state === 'connected' && st.connectedAt ? st.connectedAt * 1000 : null;
    const top = ensure(CTX.mqtt, b.name); top.conn = { kind: 'mqtt', id: b.id };
    return b;
  }
  function removeConn(id) {
    const i = BROKERS.findIndex((b) => b.id === id);
    if (i >= 0) { dropBranch(CTX.mqtt, BROKERS[i].name); BROKERS.splice(i, 1); }
    const sv = SERVERS.get(id);
    if (sv) { dropBranch(CTX.ua, sv.name); SERVERS.delete(id); }
  }
  // old links (#/ns/<broker>/<topic>, #/ua/<server>/<node>) open the matching connection tab
  function resolveLegacy() {
    const L = S.pendingLegacy; S.pendingLegacy = null;
    if (!L || !L.path) return false;
    const [first, ...rest] = L.path.split('/');
    const hit = L.kind === 'ua' ? [...SERVERS.values()].find((x) => x.name === first) : BROKERS.find((x) => x.name === first);
    if (!hit) return false;
    lensOf(`c:${hit.id}`).local = rest.join('/');
    go(`c:${hit.id}`);
    return true;
  }
  function onConnections(items) {
    const ids = new Set(items.map((x) => x.id));
    items.forEach((st) => (st.kind === 'mqtt' ? brokerFor(st) : serverFor(st)));
    [...BROKERS].forEach((b) => { if (!ids.has(b.id)) removeConn(b.id); });
    [...SERVERS.values()].forEach((x) => { if (!ids.has(x.id)) removeConn(x.id); });
    S.connsLoaded = true;
    const gone = S.tabs.filter((t) => isConnView(t) && !connOf(t));
    if (gone.length) { S.tabs = S.tabs.filter((t) => !gone.includes(t)); gone.forEach((t) => S.lens.delete(t)); }
    if (S.view === 'conn') renderConnections();
    if (S.pendingLegacy && resolveLegacy()) return;
    if (gone.includes(S.view)) { go('conn'); return; }
    if (isConnView(S.view) && !lensOf(S.view).bound) { go(S.view, false); return; }
    renderTabs();
    if (S.view === 'conn') renderConnections();
  }

  // ---------------------------------------------------------------- OPC UA (through the Witness gateway)
  function uaUnits(info) {
    if (info.units) return info.units;
    const m = /\[([^\]]+)\]\s*$/.exec(info.description || '');
    return m ? m[1] : null;
  }
  function uaDescription(info) {
    const d = (info.description || '').replace(/\s*\[[^\]]+\]\s*$/, '').trim();
    return d && d !== info.name && d !== info.displayName ? d : null;
  }
  function serverFor(st) {
    let s = SERVERS.get(st.id || st.server);
    if (!s) {
      s = { id: st.id || st.server, name: st.name || st.id, status: st, index: new Map(), total: 0, tick: 0,
        hist: { rate: [], good: [], vars: [] } };
      SERVERS.set(s.id, s);
    }
    if (st.name && s.name !== st.name) { dropBranch(CTX.ua, s.name); s.name = st.name; }
    if (st.name) s.status = { ...s.status, ...st };
    if (st.enabled === false) { s.status.state = 'disabled'; dropBranch(CTX.ua, s.name); s.index = new Map(); }
    return s;
  }
  function onUaModel(m) {
    const s = serverFor(m.status || { id: m.server });
    s.name = (m.status && m.status.name) || s.name;
    const c = CTX.ua;
    const old = c.root.children.get(s.name);
    if (old) {
      for (let a = c.root; a; a = null) a.topics -= old.topics;
      c.count -= old.topics;
      c.root.children.delete(s.name);
    }
    s.index = new Map();
    const top = ensure(c, s.name, 4); top.conn = { kind: 'ua', id: s.id };
    for (const info of m.nodes || []) {
      const n = ensure(c, `${s.name}/${info.path}`, 4);
      n.ua = info; n.server = s.id;
      s.index.set(info.id, n);
      if (info.nodeClass === 'Variable') { n.uaVar = true; n.units = uaUnits(info); }
    }
    for (const v of m.values || []) applyUa(s, v, true);
    c.treeDirty = true; c.viewDirty = true;
    if (S.view === 'conn') renderConnections();
    if (S.view === 'atlas' && !S.agent.server) buildPage();
  }
  function applyUa(s, item, initial) {
    const n = s.index.get(item.id); if (!n) return;
    const c = CTX.ua; const now = Date.now();
    const info = n.ua;
    const tvq = { Value: item.v, Quality: item.q ? item.q.name : 'Good', Timestamp: item.st || item.svt };
    if (n.units) tvq.UOM = n.units;
    const key = info.displayName || info.name;
    const dv = { value: item.v, status: item.q ? item.q.name : 'Good', statusCode: item.q ? item.q.code : 0, sourceTimestamp: item.st, serverTimestamp: item.svt };
    const text = JSON.stringify(dv);
    markPayload(c, n);
    n.raw = text; n.prevJson = n.json; n.json = dv; n.count++; n.last = now;
    n.quality = item.q ? item.q.severity : 'good';
    n.history.unshift({ t: now, raw: text, retained: false });
    if (n.history.length > 60) n.history.pop();
    n.view = { [key]: tvq };
    record(n, n.view, now);
    const p = n.parent;
    if (p && p !== c.root && !p.conn) { p.view = merge(p.view || {}, { [key]: tvq }); record(p, { [key]: tvq }, now); }
    touch(c, n, now);
    if (!initial) { c.tick++; s.tick++; s.total++; feedPush(s.id, 'ua', n.path, `${fmtVal(item.v)}${n.units ? ` ${n.units}` : ''}  ${tvq.Quality}`); }
  }
  let uaSocket = null; let uaBackoff = 1000; let uaUrl = '';
  function connectUa() {
    if (!uaUrl) return;
    try { uaSocket = new WebSocket(uaUrl); } catch { scheduleUa(); return; }
    S.uaSocket = 'connecting';
    uaSocket.onopen = () => { uaBackoff = 1000; S.uaSocket = 'open'; };
    uaSocket.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.type === 'connections') onConnections(m.items);
      else if (m.type === 'servers') m.servers.forEach(serverFor);
      else if (m.type === 'model') onUaModel(m);
      else if (m.type === 'status') { if (m.kind === 'mqtt') brokerFor(m); else serverFor(m); if (S.view === 'conn') renderConnections(); }
      else if (m.type === 'values') { const sv = SERVERS.get(m.server); if (sv) m.items.forEach((it) => applyUa(sv, it, false)); }
      else if (m.type === 'mqtt' || m.type === 'mqtt_snapshot') { const b = BROKERS.find((x) => x.id === m.conn); if (b) m.msgs.forEach((x) => onMqtt(b, x, m.type === 'mqtt_snapshot')); }
      else if (m.type === 'removed') {
        if (m.replaced) {
          const b = BROKERS.find((x) => x.id === m.id); if (b) { dropBranch(CTX.mqtt, b.name); b.sys = {}; }
          const sv = SERVERS.get(m.id); if (sv) { dropBranch(CTX.ua, sv.name); sv.index = new Map(); }
        } else removeConn(m.id);
        if (S.view === 'conn') renderConnections();
      }
    };
    uaSocket.onclose = () => { S.uaSocket = 'closed'; scheduleUa(); };
    uaSocket.onerror = () => { try { uaSocket.close(); } catch { /* ignore */ } };
  }
  function scheduleUa() { setTimeout(connectUa, uaBackoff); uaBackoff = Math.min(uaBackoff * 2, 30000); }
  setInterval(() => { if (uaSocket && uaSocket.readyState === 1) uaSocket.send('ping'); }, 10000);
  function uaState(s) {
    if (S.uaSocket !== 'open') return S.uaSocket === 'connecting' ? 'connecting' : 'offline';
    return (s && s.status && s.status.state) || 'connecting';
  }
  const dotFor = (state) => (state === 'connected' ? 'ok' : state === 'disabled' ? '' : ['connecting', 'browsing', 'starting'].includes(state) ? 'warn' : 'bad');

  // ---------------------------------------------------------------- view model
  function viewParts(view) {
    const tv = []; const attrs = []; const recs = []; const env = {};
    if (!isObj(view)) return { tv, attrs, recs, env };
    for (const k of Object.keys(view)) {
      const v = view[k];
      if (ENVELOPE.has(k)) env[k] = v;
      else if (isTVQ(v)) tv.push({ key: k, val: pick(v, 'value'), q: quality(pick(v, 'quality')), ts: Date.parse(pick(v, 'timestamp')) || null, uom: pick(v, 'uom') });
      else if (isObj(v) || Array.isArray(v)) recs.push({ key: k, val: v });
      else if (typeof v === 'number') tv.push({ key: k, val: v, q: null, ts: null });
      else attrs.push({ key: k, val: v });
    }
    return { tv, attrs, recs, env };
  }
  function spark(arr, w = 120, h = 28, area = true) {
    if (!arr || arr.length < 2) return '';
    const t0 = arr[0].t; const t1 = arr[arr.length - 1].t || t0 + 1;
    let lo = Infinity; let hi = -Infinity;
    for (const p of arr) { if (p.v < lo) lo = p.v; if (p.v > hi) hi = p.v; }
    if (hi === lo) { hi += 1; lo -= 1; }
    const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
    const Y = (v) => h - 2 - ((v - lo) / (hi - lo)) * (h - 4);
    const d = arr.map((p, i) => `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join('');
    return `${area ? `<path class="area" d="${d}L${w},${h}L0,${h}Z"/>` : ''}<path class="line" d="${d}"/>`;
  }
  const sparkSvg = (arr) => (arr && arr.length > 1 ? `<svg class="spark" viewBox="0 0 120 28" preserveAspectRatio="none">${spark(arr)}</svg>` : '');
  // tile sparkline over plain 1 s samples; flat lines sit at the bottom like the Historian's
  function tileSpark(vals) {
    const arr = (vals || []).filter((v) => Number.isFinite(v));
    if (arr.length < 2) return '<svg class="tile-spark" viewBox="0 0 120 36" preserveAspectRatio="none"></svg>';
    const lo = Math.min(...arr); const hi = Math.max(...arr);
    const pts = arr.map((v, i) => [(i / (arr.length - 1)) * 120, hi === lo ? 34 : 35 - ((v - lo) / (hi - lo)) * 30]);
    const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
    return `<svg class="tile-spark" viewBox="0 0 120 36" preserveAspectRatio="none"><path class="area" d="${d}L120,36L0,36Z"/><path class="line" d="${d}"/></svg>`;
  }

  function bigChart(n, key, units) {
    const arr = n.series.get(key) || [];
    const title = key ? humanize(key) : 'Value';
    if (arr.length < 2) {
      return `<div class="card"><div class="chart-head"><b>${esc(title)}</b><span>Trend since this page opened</span></div><div class="chart-empty">Collecting values. The trend draws after the second update.</div></div>`;
    }
    const W = 800; const H = 200;
    const t0 = arr[0].t; const t1 = Math.max(arr[arr.length - 1].t, t0 + 1);
    let lo = Infinity; let hi = -Infinity;
    for (const p of arr) { if (p.v < lo) lo = p.v; if (p.v > hi) hi = p.v; }
    const padv = (hi - lo) * 0.1 || Math.abs(hi) * 0.05 || 1; lo -= padv; hi += padv;
    const X = (t) => ((t - t0) / (t1 - t0)) * W;
    const Y = (v) => H - ((v - lo) / (hi - lo)) * H;
    const d = arr.map((p, i) => `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join('');
    const grid = [0.25, 0.5, 0.75].map((f) => `<line class="grid-line" x1="0" x2="${W}" y1="${H * f}" y2="${H * f}"/>`).join('');
    const ylab = [0, 0.5, 1].map((f) => `<span class="yl" style="top:calc(${f} * (100% - 18px))">${fmtNum(hi - (hi - lo) * f)}</span>`).join('');
    const last = arr[arr.length - 1];
    return `<div class="card"><div class="chart-head"><b>${esc(title)}</b><span>${arr.length} points · last ${fmtNum(last.v)}${units ? ` ${esc(units)}` : ''} at ${fmtTime(last.t)}</span></div>
      <div class="chart-body">${ylab}
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<path class="area" d="${d}L${W},${H}L0,${H}Z"/><path class="line" d="${d}"/></svg>
        <span class="xl" style="left:54px">${fmtTime(t0)}</span><span class="xl" style="right:0">${fmtTime(t1)}</span>
      </div></div>`;
  }
  const stat = (lbl, val, attr = '') => `<div class="stat"><span class="lbl">${esc(lbl)}</span><span class="val"${attr}>${esc(val)}</span></div>`;
  const rate = (c) => c.rateHist[c.rateHist.length - 1] || 0;
  const last = (arr) => (arr && arr.length ? arr[arr.length - 1] : NaN);
  function connCount(k) {
    if (!k) return 0;
    if (k.kind === 'ua') return (k.s.status && k.s.status.variables) || 0;
    const top = find(CTX.mqtt, k.name); return top ? visTopics(top) : 0;
  }
  function statsHtml() {
    const k = connOf(S.view);
    if (k && k.kind === 'ua') return stat('Variables', fmtNum(connCount(k))) + stat('Updates/s', fmtNum(last(k.s.hist.rate) || 0)) + stat('Received', fmtNum(k.s.total));
    if (k) return stat('Topics', fmtNum(connCount(k))) + stat('Messages/s', fmtNum(last(k.b.hist.rate) || 0)) + stat('Received', fmtNum(k.b.total));
    if (isConnView(S.view)) return '';
    if (S.view === 'conn') {
      const up = BROKERS.filter((b) => b.conn === 'connected').length + [...SERVERS.values()].filter((s) => uaState(s) === 'connected').length;
      return stat('Connected', `${up} of ${BROKERS.length + SERVERS.size}`) + stat('MQTT msgs/s', fmtNum(rate(CTX.mqtt))) + stat('OPC UA updates/s', fmtNum(rate(CTX.ua)));
    }
    return '';
  }

  // ---------------------------------------------------------------- tree
  function sortKids(c, n) {
    return [...n.children.values()]
      .filter((k) => c.showSys || k.name !== '$SYS')
      .sort((a, b) => (b.children.size > 0) - (a.children.size > 0) || (c.key === 'ua' && n !== c.root ? 0 : a.name.localeCompare(b.name, undefined, { numeric: true })));
  }
  function matches(n, f, memo) {
    if (memo.has(n)) return memo.get(n);
    let m = n.path.toLowerCase().includes(f);
    if (!m) for (const k of n.children.values()) if (matches(k, f, memo)) { m = true; break; }
    memo.set(n, m); return m;
  }
  function connState(n) {
    if (!n.conn) return null;
    if (n.conn.kind === 'mqtt') { const b = BROKERS.find((x) => x.id === n.conn.id); return b ? b.conn : 'offline'; }
    return uaState(SERVERS.get(n.conn.id));
  }
  function preview(n) {
    if (n.conn) { const st = connState(n); return `<span class="pv">${esc(st === 'connected' ? '' : humanize(st))}</span>`; }
    if (n.uaVar && n.view) {
      const v = Object.values(n.view)[0];
      return `<span class="pv"><b>${esc(fmtVal(v.Value))}</b>${n.units ? ` ${esc(n.units)}` : ''}</span>`;
    }
    if (n.ua && !n.uaVar) return '';
    if (n.children.size && !n.raw && !n.view) return '';
    if (n.view) {
      const { tv } = viewParts(n.view);
      const first = tv.find((x) => x.val !== null && x.val !== undefined);
      if (first) return `<span class="pv">${esc(humanize(first.key))} <b>${esc(fmtVal(first.val))}</b></span>`;
      return `<span class="pv">${Object.keys(n.view).length} fields</span>`;
    }
    if (n.raw !== null) return `<span class="pv"><b>${esc(oneLine(n.raw, 28) || '∅')}</b></span>`;
    return '';
  }
  const scopeTop = () => { const k = connOf(S.view); return k ? find(ctxOf(S.view), k.name) : null; };
  function emptyTreeText(c) {
    if (c.filter) return 'Nothing matches the filter.';
    const k = connOf(S.view);
    if (k) {
      const st = k.kind === 'ua' ? uaState(k.s) : k.b.conn;
      if (st !== 'connected') return `${k.name} is ${humanize(st || 'connecting').toLowerCase()}.`;
      return k.kind === 'ua' ? 'Browsing the address space.' : 'Waiting for the first messages.';
    }
    if (c.key === 'ua') return S.uaSocket === 'open' ? 'No OPC UA servers are configured on the gateway.' : 'Witness gateway unreachable. Retrying.';
    return BROKERS.length ? 'Waiting for the brokers.' : 'No brokers are configured.';
  }
  function renderTree() {
    const el = $('#tree'); if (!el) return;
    const c = cur();
    const f = c.filter.trim().toLowerCase();
    const memo = new Map(); const out = []; const now = Date.now();
    const walk = (n, depth) => {
      for (const k of sortKids(c, n)) {
        if (f && !matches(k, f, memo)) continue;
        const kids = k.children.size > 0;
        const open = f ? true : c.expanded.has(k.path);
        const heat = Math.max(0, 1 - (now - k.activity) / 2500).toFixed(2);
        const lead = k.conn ? `<span class="dot ${dotFor(connState(k))}"></span>` : `<span class="heat" style="--h:${heat}"></span>`;
        out.push(`<div class="row${kids ? ' folder' : ''}${k.conn ? ' conn-row' : ''}${k.path === c.selected ? ' sel' : ''}" role="treeitem" data-act="sel" data-path="${esc(k.path)}" style="--d:${depth}">
          <span class="tw${kids ? '' : ' none'}${open ? ' open' : ''}" data-act="tog" data-path="${esc(k.path)}">${icon('chevronRight', 'ic-sm')}</span>
          ${lead}
          <span class="nm">${esc(k.name === '' ? '(empty)' : k.name)}</span>
          ${preview(k)}
          ${kids ? `<span class="cnt" title="${c.key === 'ua' ? 'Variables' : 'Topics'} under this branch">${c.showSys ? k.topics : visTopics(k)}</span>` : ''}
        </div>`);
        if (open && kids) walk(k, depth + 1);
      }
    };
    const top = scopeTop();
    if (top) walk(top, 0);
    el.innerHTML = out.join('') || `<div class="tree-empty">${emptyTreeText(c)}</div>`;
  }

  // ---------------------------------------------------------------- detail (shared by MQTT and OPC UA)
  function crumbs(c, path) {
    const parts = path ? path.split('/') : [];
    const items = parts.map((p, i) => `${i ? '<span class="sep">/</span>' : ''}<button data-act="sel" data-path="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p || '(empty)')}</button>`);
    return `<nav class="crumbs">${items.join('')}</nav>`;
  }
  function connCaption(n) {
    if (n.conn.kind === 'mqtt') { const b = BROKERS.find((x) => x.id === n.conn.id); return b ? b.url : ''; }
    const s = SERVERS.get(n.conn.id); return s ? s.status.endpoint : '';
  }
  function childCard(c, k) {
    const { tv, attrs } = viewParts(k.view);
    const sub = attrs.filter((a) => typeof a.val === 'string' && !ISO.test(a.val) && a.val !== k.name).slice(0, 2).map((a) => a.val).join(' · ');
    let body = '';
    if (k.uaVar && tv.length) {
      const x = tv[0];
      body = `<div class="vrow"><span class="vl">${x.q ? `<span class="dot ${x.q.cls === 'good' ? 'ok' : x.q.cls === 'unc' ? 'warn' : 'bad'}" title="${x.q.label}"></span>` : ''}${esc(k.ua.dataType || 'Value')}</span><span class="vv">${esc(fmtVal(x.val))}${k.units ? ` ${esc(k.units)}` : ''}</span>${sparkSvg(k.series.get(x.key))}</div>`;
    } else if (tv.length) {
      body = tv.slice(0, 4).map((x) => `<div class="vrow"><span class="vl">${x.q ? `<span class="dot ${x.q.cls === 'good' ? 'ok' : x.q.cls === 'unc' ? 'warn' : 'bad'}" title="${x.q.label}"></span>` : ''}${esc(humanize(x.key))}</span><span class="vv">${esc(fmtVal(x.val))}${x.uom ? ` <small>${esc(x.uom)}</small>` : ''}</span>${sparkSvg(k.series.get(x.key))}</div>`).join('');
    } else if (k.view) {
      body = `<dl class="kv">${attrs.slice(0, 4).map((a) => `<dt>${esc(humanize(a.key))}</dt><dd>${esc(fmtVal(a.val))}</dd>`).join('')}</dl>`;
    } else if (k.raw !== null && !k.children.size) {
      body = `<div class="vrow"><span class="vl">Payload</span><span class="vv">${esc(oneLine(k.raw, 24))}</span>${sparkSvg(k.series.get(''))}</div>`;
    } else {
      const names = sortKids(c, k).slice(0, 8).map((x) => `<span class="chip">${esc(x.name)}</span>`).join('');
      body = `<div class="chips">${names}${k.children.size > 8 ? `<span class="chip">+${k.children.size - 8}</span>` : ''}</div>`;
    }
    const isLeaf = k.uaVar || (k.raw !== null && !k.children.size);
    const kind = k.conn ? (k.conn.kind === 'ua' ? 'cpu' : 'server') : k.uaVar ? 'tag' : (k.view || isLeaf ? 'box' : 'folder');
    const unit = c.key === 'ua' ? 'variable' : 'topic';
    let foot;
    if (k.children.size && !k.view) { const t = visTopics(k); foot = `${t} ${unit}${t === 1 ? '' : 's'}`; }
    else if (k.uaVar) foot = k.ua.writable ? 'Writable' : 'Read-only';
    else if (k.ua) foot = `${k.topics} variable${k.topics === 1 ? '' : 's'}`;
    else foot = k.retained || k.hasState ? 'Retained state' : `${k.count} message${k.count === 1 ? '' : 's'}`;
    let fallback;
    if (k.conn) fallback = connCaption(k);
    else if (k.uaVar) fallback = uaDescription(k.ua) || k.ua.id;
    else if (k.ua) fallback = uaDescription(k.ua) || `${k.children.size} ${k.children.size === 1 ? 'node' : 'nodes'} below`;
    else fallback = k.children.size && !k.view ? `${k.children.size} ${k.children.size === 1 ? 'item' : 'items'} below` : (k.hasState ? 'Asset with retained state' : 'Live topic');
    const title = k.conn ? `<span class="dot ${dotFor(connState(k))}"></span>${esc(k.name)}` : esc(k.name || '(empty)');
    return `<div class="card click" data-act="sel" data-path="${esc(k.path)}">
      <div class="card-top">${k.conn ? '' : icon(kind, 'ic-sm')}<span class="card-title">${title}</span></div>
      <div class="card-sub">${esc(sub || fallback)}</div>
      ${body}
      <div class="card-foot"><span>${foot}</span><span data-ago="${k.activity}">${ago(k.activity)}</span></div>
    </div>`;
  }
  function folderDetail(c, n) {
    const kids = sortKids(c, n);
    const isRoot = n === c.root;
    const ua = c.key === 'ua';
    if (isRoot && !kids.length) {
      return `<div class="empty-state">${icon(ua ? 'cpu' : 'radio')}<h2>${esc(emptyTreeText(c))}</h2><p>${ua ? 'Servers appear as soon as the gateway has browsed them.' : 'Topics appear as soon as the first messages or retained values arrive.'}</p></div>`;
    }
    let title; let sub; let lead;
    if (isRoot) { title = ua ? 'All servers' : 'All brokers'; sub = ''; lead = icon(ua ? 'cpu' : 'server'); }
    else if (n.conn) {
      title = n.name; lead = `<span class="dot ${dotFor(connState(n))}"></span>`;
      sub = `<div class="pathline"><code>${esc(connCaption(n))}</code><button class="icon-sm" data-act="copy" data-text="${esc(connCaption(n))}" title="Copy address">${icon('copy', 'ic-sm')}</button></div>`;
    } else {
      title = (n.ua ? n.ua.displayName : n.name) || '(empty)'; lead = icon('folder');
      const ident = n.ua ? n.ua.id : `${localPath(n)}/#`;
      sub = `<div class="pathline"><code>${esc(ident)}</code><button class="icon-sm" data-act="copy" data-text="${esc(ident)}" title="${ua ? 'Copy NodeId' : 'Copy subscription filter'}">${icon('copy', 'ic-sm')}</button></div>`;
    }
    return `${crumbs(c, n.path)}<div class="d-head">
        <div><h2>${lead}${esc(title)}</h2>${sub}</div>
        <div class="stats">${stat(ua ? 'Variables' : 'Topics', fmtNum(isRoot ? c.count : visTopics(n)))}${stat(ua ? 'Updates' : 'Messages', fmtNum(isRoot ? c.total : n.sub))}${stat('Last activity', ago(n.activity), ` data-ago="${n.activity}"`)}</div>
      </div>
      <div class="sec"><div class="sec-h"><span class="lbl">${isRoot ? (ua ? 'Servers' : 'Brokers') : 'Contents'}</span><span class="note">Select a card to drill in</span></div>
        <div class="grid">${kids.map((k) => childCard(c, k)).join('')}</div></div>`;
  }
  function topicDetail(c, n) {
    const ua = n.ua;
    const own = n.raw !== null;
    const { tv, attrs, recs, env } = viewParts(n.view);
    const numeric = tv.filter((x) => typeof x.val === 'number' || typeof x.val === 'boolean');
    if (!n.selProp || !n.series.has(n.selProp)) n.selProp = (numeric[0] && numeric[0].key) || (n.series.has('') ? '' : null);
    const others = sortKids(c, n).filter((k) => !(k.name === 'state' && n.hasState) && !(ua && k.uaVar));
    const stateNode = n.hasState ? n.children.get('state') : null;
    const tags = ua ? [
      `<span class="tag info">OPC UA ${n.uaVar ? 'Variable' : 'Object'}</span>`,
      ua.dataType ? `<span class="tag">${esc(ua.dataType)}</span>` : '',
      n.uaVar ? `<span class="tag">${ua.writable ? 'Writable' : 'Read-only'}</span>` : '',
      n.units ? `<span class="tag">${esc(n.units)}</span>` : '',
    ].join('') : [
      n.retained ? '<span class="tag info">Retained</span>' : '',
      stateNode ? '<span class="tag info">Retained state</span>' : '',
      own ? `<span class="tag">QoS ${n.qos}</span>` : '',
      own ? `<span class="tag">${n.json !== undefined ? 'JSON' : 'Text'}</span>` : '',
      env.instanceUri ? `<span class="tag">Atlas instance ${esc(env.instanceUri)}</span>` : '',
    ].join('');
    const ident = ua ? ua.id : localPath(n);
    const statBlock = ua
      ? `${stat(n.uaVar ? 'Updates' : 'Variables', fmtNum(n.uaVar ? n.count : n.topics))}${stat('Last update', ago(n.activity), ` data-ago="${n.activity}"`)}`
      : `${stat('Messages', fmtNum(n.count + (stateNode ? stateNode.count : 0)))}${stat('Last update', ago(n.activity), ` data-ago="${n.activity}"`)}${env.emitTime ? stat('Emitted', fmtTime(Date.parse(env.emitTime))) : ''}`;
    let html = `${crumbs(c, n.path)}<div class="d-head">
        <div><h2>${icon(n.uaVar ? 'tag' : 'box')}${esc(ua ? ua.displayName : n.name || '(empty)')}</h2>
          <div class="pathline"><code>${esc(ident)}</code><button class="icon-sm" data-act="copy" data-text="${esc(ident)}" title="${ua ? 'Copy NodeId' : 'Copy topic'}">${icon('copy', 'ic-sm')}</button></div>
          <div class="tags">${tags}</div>
        </div>
        <div class="stats">${statBlock}</div>
      </div>`;

    if (n.view) {
      if (tv.length) {
        const note = ua && !n.uaVar ? 'Every variable under this object, updating live. Select a value to trend it.' : 'Current state, merged from every message. Select a value to trend it.';
        html += `<div class="sec"><div class="sec-h"><span class="lbl">Live values</span><span class="note">${note}</span></div><div class="grid">`;
        html += tv.map((x) => {
          const trend = typeof x.val === 'number' || typeof x.val === 'boolean';
          return `<div class="card tvq${trend ? ' click' : ' str'}${x.key === n.selProp ? ' sel' : ''}" ${trend ? `data-act="prop" data-key="${esc(x.key)}"` : ''}>
            <div class="card-top"><span class="card-title">${esc(humanize(x.key))}</span><button class="icon-sm card-cp" data-act="cpval" data-key="${esc(x.key)}" title="Copy value">${icon('copy', 'ic-sm')}</button></div>
            <div class="big">${esc(fmtVal(x.val))}${x.uom ? ` <span class="card-sub">${esc(x.uom)}</span>` : ''}</div>
            <div class="meta">${x.q ? `<span class="qpill ${x.q.cls}">${x.q.label}</span>` : ''}${x.ts ? `<span title="Source timestamp">${esc(fmtTime(x.ts))}</span><span data-ago="${x.ts}">${ago(x.ts)}</span>` : ''}</div>
            ${sparkSvg(n.series.get(x.key))}
          </div>`;
        }).join('');
        html += '</div></div>';
      }
      if (n.selProp !== null) {
        const t = tv.find((x) => x.key === n.selProp);
        html += `<div class="sec">${bigChart(n, n.selProp, t && t.uom)}</div>`;
      }
      if (ua) {
        const rows = [['NodeId', ua.id], ['Server', topOf(n).name], ['Browse path', localPath(n)], ['Node class', ua.nodeClass], ['Data type', ua.dataType], ['Access', n.uaVar ? (ua.writable ? 'Read and write' : 'Read only') : null], ['Units', n.units], ['Description', uaDescription(ua)]].filter(([, v]) => v);
        html += `<div class="sec"><div class="sec-h"><span class="lbl">Node</span></div><div class="card"><dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="cp" data-act="cptext" data-text="${esc(v)}" data-what="${esc(k)}" title="Copy ${esc(k)}">${esc(v)}</dd>`).join('')}</dl></div></div>`;
      } else if (attrs.length) {
        html += `<div class="sec"><div class="sec-h"><span class="lbl">Attributes</span></div><div class="card"><dl class="kv">${attrs.map((a) => `<dt>${esc(humanize(a.key))}</dt><dd class="cp${a.val === null ? ' null' : ''}" data-act="cptext" data-text="${esc(valText(a.val))}" data-what="${esc(humanize(a.key))}" title="Copy ${esc(humanize(a.key))}">${esc(fmtVal(a.val))}</dd>`).join('')}</dl></div></div>`;
      }
      if (recs.length) {
        html += `<div class="sec"><div class="sec-h"><span class="lbl">Records</span><span class="note">Latest related record from the model</span></div><div class="grid">`;
        html += recs.map((r) => {
          const entries = Array.isArray(r.val) ? r.val.map((v, i) => [String(i), v]) : Object.entries(r.val);
          const empty = entries.every(([, v]) => v === null);
          return `<div class="card"><div class="card-top"><span class="card-title">${esc(humanize(r.key))}</span>${empty ? '' : `<button class="icon-sm card-cp" data-act="cptext" data-text="${esc(JSON.stringify(r.val, null, 2))}" data-what="${esc(humanize(r.key))} record" title="Copy record as JSON">${icon('copy', 'ic-sm')}</button>`}</div>
            ${empty ? '<div class="card-sub">No record</div>' : `<dl class="kv" style="margin-top:8px">${entries.map(([k, v]) => `<dt>${esc(humanize(k))}</dt><dd class="cp${v === null ? ' null' : ''}" data-act="cptext" data-text="${esc(valText(v))}" data-what="${esc(humanize(k))}" title="Copy ${esc(humanize(k))}">${esc(fmtVal(v))}</dd>`).join('')}</dl>`}</div>`;
        }).join('');
        html += '</div></div>';
      }
    } else if (own) {
      html += `<div class="sec"><div class="sec-h"><span class="lbl">Current value</span><span class="spacer"></span><button class="icon-sm" data-act="cptext" data-text="${esc(n.raw)}" data-what="value" title="Copy value">${icon('copy', 'ic-sm')}</button></div><div class="card"><div class="textval">${esc(n.raw === '' ? '(empty payload)' : n.raw)}</div></div></div>`;
      if (n.series.has('')) html += `<div class="sec">${bigChart(n, '')}</div>`;
    }

    const src = own ? n : stateNode;
    if (src && src.raw !== null) {
      const ch = c.tab === 'latest' && src.json !== undefined ? changedPaths(src.prevJson, src.json) : new Set();
      const body = c.tab === 'latest'
        ? `<pre class="json">${src.json !== undefined ? jsonHtml(src.json, '', ch, 0) : esc(src.raw)}</pre>`
        : `<div class="list">${src.history.map((h) => `<div class="li hist-li"><span class="t">${fmtTime(h.t, true)}</span><span class="r" title="${h.retained ? 'Retained' : ''}">${h.retained ? 'R' : ''}</span><span class="p" title="${esc(oneLine(h.raw, 2000))}">${esc(oneLine(h.raw) || '(empty)')}</span><button class="icon-sm row-cp" data-act="cphist" data-t="${h.t}" title="Copy this message">${icon('copy', 'ic-sm')}</button></div>`).join('')}</div>`;
      const label = ua ? 'Data value' : 'Payload';
      const note = ua ? 'Latest DataValue from the subscription' : (src === n ? 'Latest message on this topic' : `Retained message on ${esc(localPath(src))}`);
      html += `<div class="sec"><div class="sec-h"><span class="lbl">${label}</span><span class="note">${note}${src.json !== undefined && c.tab === 'latest' ? ' · click a key or value to copy it' : ''}</span><span class="spacer"></span><button class="btn btn-outline btn-sm" data-act="pmenu" title="Copy options">${icon('copy', 'ic-sm')}Copy${icon('chevronDown', 'ic-sm')}</button></div>
        <div class="seg"><button class="${c.tab === 'latest' ? 'on' : ''}" data-act="tab" data-tab="latest">Latest</button><button class="${c.tab === 'history' ? 'on' : ''}" data-act="tab" data-tab="history">History (${src.history.length})</button></div>${body}</div>`;
    }
    if (others.length) html += `<div class="sec"><div class="sec-h"><span class="lbl">${ua ? 'Child objects' : 'Sub-topics'}</span></div><div class="grid">${others.map((k) => childCard(c, k)).join('')}</div></div>`;
    return html;
  }
  function renderDetail() {
    const el = $('#detail'); if (!el) return;
    const c = cur();
    const top = scopeTop();
    if (!top) { el.innerHTML = `<div class="empty-state">${icon('plug')}<h2>${esc(emptyTreeText(c))}</h2></div>`; return; }
    let n = find(c, c.selected);
    if (!n || (n !== top && !n.path.startsWith(`${top.path}/`))) n = top;
    el.innerHTML = n !== top && (n.view || n.raw !== null) ? topicDetail(c, n) : folderDetail(c, n);
  }

  // ---------------------------------------------------------------- connections (one list for brokers and servers, like Datasets)
  function connEntries() {
    const out = BROKERS.map((b) => ({ key: `mqtt:${b.id}`, kind: 'mqtt', b }));
    for (const s of SERVERS.values()) out.push({ key: `ua:${s.id}`, kind: 'ua', s });
    const f = S.connFilter.trim().toLowerCase();
    return f ? out.filter((e) => (e.b ? `${e.b.name} ${e.b.url} mqtt` : `${e.s.name} ${e.s.status.endpoint} opc ua`).toLowerCase().includes(f)) : out;
  }
  const cfgCell = (label, value, caption) => `<div class="cfg"><div class="lbl">${esc(label)}</div><div class="cfg-val">${esc(value)}</div><div class="cfg-cap">${esc(caption || '')}</div></div>`;
  const tile = (label, value, unit, hist) => `<div class="tile"><div class="lbl">${esc(label)}</div><div class="tile-val"><b>${esc(value)}</b>${unit ? `<span>${esc(unit)}</span>` : ''}</div>${tileSpark(hist)}</div>`;
  function mqttSecurityText(st) {
    const sec = st && st.security;
    if (!sec || !sec.tls) return 'no TLS';
    return `TLS${sec.verify ? ', certificate verified' : ', certificate not verified'}${sec.clientCert ? ', client certificate' : ''}`;
  }
  function uaSecurityText(st) {
    const sec = st && st.security;
    if (!sec || sec.policy === 'None') return 'security policy None';
    return `${sec.policy} · ${sec.mode === 'SignAndEncrypt' ? 'sign and encrypt' : 'sign'}${sec.pinned ? ' · server certificate pinned' : ''}`;
  }
  function secureBadge(e) {
    const sec = e.b ? e.b.status && e.b.status.security : e.s.status && e.s.status.security;
    const on = sec && (e.b ? sec.tls : sec.policy && sec.policy !== 'None');
    return on ? ` <span class="sec-badge">${icon('lock', 'ic-xs')}${e.b ? 'TLS' : 'Secure'}</span>` : '';
  }
  function connRow(e) {
    const open = S.openConn.has(e.key);
    let name; let state; let typeLabel; let cols; let cfg; let tiles;
    if (e.kind === 'mqtt') {
      const b = e.b; const sys = (k) => { const v = parseFloat(b.sys[k]); return Number.isFinite(v) ? v : NaN; };
      name = b.name; state = b.conn; typeLabel = 'MQTT broker';
      const top = find(CTX.mqtt, b.name);
      const sysNode = top && top.children.get('$SYS');
      const topics = top ? top.topics - (sysNode ? sysNode.topics : 0) : 0;
      cols = [['Messages/s', fmtNum(last(b.hist.rate) || 0)], ['Clients', Number.isFinite(sys('broker/clients/connected')) ? fmtNum(sys('broker/clients/connected')) : '—'], ['Topics', fmtNum(topics)]];
      cfg = [
        cfgCell('Endpoint', b.url || '—', mqttSecurityText(b.status)),
        cfgCell('Signed in as', b.username || 'Anonymous', b.username ? 'user name and password' : 'no credentials'),
        cfgCell('Topics', (b.status && b.status.topics || []).filter((t) => !t.startsWith('$SYS')).join(', ') || '#', `${fmtNum(b.status ? b.status.cachedTopics || 0 : 0)} topics cached by the gateway`),
        cfgCell('Broker', b.sys['broker/version'] ? b.sys['broker/version'].replace(/^mosquitto version /i, 'Mosquitto ') : '—', b.since ? `up ${duration(sys('broker/uptime'))} · connected ${ago(b.since)}` : (b.error || (b.conn === 'disabled' ? 'disabled' : 'not connected'))),
      ];
      tiles = [
        tile('Messages/s', fmtNum(last(b.hist.rate) || 0), 'msg/s', b.hist.rate),
        tile('Received', fmtNum(sys('broker/load/messages/received/1min')), '/min', b.hist.recv),
        tile('Sent', fmtNum(sys('broker/load/messages/sent/1min')), '/min', b.hist.sent),
        tile('Clients', fmtNum(sys('broker/clients/connected')), 'connected', b.hist.clients),
        tile('Retained', fmtNum(sys('broker/retained messages/count')), 'msgs', b.hist.retained),
        tile('Data in', bytes(sys('broker/load/bytes/received/1min')).replace(/ .*/, ''), `${bytes(sys('broker/load/bytes/received/1min')).replace(/^[^ ]* /, '')}/min`, b.hist.bytesIn),
      ];
    } else {
      const s = e.s; const st = s.status || {};
      name = s.name; state = uaState(s); typeLabel = 'OPC UA server';
      const vars = st.variables || 0;
      cols = [['Updates/s', fmtNum(last(s.hist.rate) || 0)], ['Variables', fmtNum(vars)], ['Nodes', fmtNum(st.nodes || 0)]];
      const si = st.serverInfo || {};
      cfg = [
        cfgCell('Endpoint', (st.endpoint || '').replace(/^opc\.tcp:\/\//, ''), uaSecurityText(st)),
        cfgCell('Signed in as', st.user || 'Anonymous', st.user ? 'user name and password' : 'anonymous'),
        cfgCell('Server', si.product ? `${si.product} ${si.version || ''}`.trim() : '—', si.manufacturer || ''),
        cfgCell('Publishing', st.publishMs ? `${st.publishMs} ms` : '—', 'subscription interval'),
      ];
      const good = last(s.hist.good);
      tiles = [
        tile('Updates/s', fmtNum(last(s.hist.rate) || 0), 'upd/s', s.hist.rate),
        tile('Variables', fmtNum(vars), 'subscribed', s.hist.vars),
        tile('Good quality', Number.isFinite(good) ? fmtNum(good) : '—', '%', s.hist.good),
        tile('Objects', fmtNum((st.nodes || 0) - vars), 'total', null),
        tile('Connected', st.connectedAt && state === 'connected' ? duration(Date.now() / 1000 - st.connectedAt) : '—', '', null),
        tile('Gateway updates', fmtNum(st.updates || 0), 'total', null),
      ];
      if (st.error && state !== 'connected') cfg[3] = cfgCell('Last error', oneLine(st.error, 60), 'retrying with backoff');
    }
    return `<div class="acc${open ? ' open' : ''}">
      <div class="acc-head" data-act="connopen" data-id="${esc(e.b ? e.b.id : e.s.id)}" title="Open ${esc(name)} in a new tab">
        <button class="acc-chev" data-act="conn" data-key="${esc(e.key)}" aria-label="${open ? 'Hide' : 'Show'} settings and live status for ${esc(name)}" title="${open ? 'Hide' : 'Show'} settings and live status">${icon('chevronRight', 'ic-sm')}</button>
        <span class="acc-name"><span class="dot ${dotFor(state)}" title="${esc(humanize(state))}"></span><b>${esc(name)}</b><span class="acc-type">${typeLabel}${state === 'disabled' ? ' · disabled' : ''}${secureBadge(e)}</span></span>
        ${cols.map(([l, v]) => stat(l, v)).join('')}
        <button class="icon-btn acc-edit" data-act="connedit" data-id="${esc(e.b ? e.b.id : e.s.id)}" title="Edit ${esc(name)}">${icon('pencil', 'ic-sm')}</button>
      </div>
      ${open ? `<div class="acc-body">
        <div class="cfg-grid">${cfg.join('')}</div>
        <div class="live-h"><span class="lbl">Live status</span><span class="cfg-cap">last 5 min</span></div>
        <div class="tiles">${tiles.join('')}</div>
      </div>` : ''}
    </div>`;
  }
  function renderConnections() {
    const el = $('#connList'); if (!el) return;
    const list = connEntries();
    el.innerHTML = list.length ? `<div class="accordion">${list.map(connRow).join('')}</div>`
      : `<div class="empty-state">${icon('plug')}<h2>${S.connFilter ? 'Nothing matches the filter' : 'No connections'}</h2></div>`;
  }

  // ---------------------------------------------------------------- Add / edit connection panel
  // Same edit panel as the other Timebase 2.0 apps (Historian "Edit dataset"): a 450px card floating over the
  // right of the page, draggable by its header, label | value | info rows, Discard / Save in the header and
  // "N pending" + Delete in the footer. The page behind it stays usable.
  const DLG_DEFAULTS = {
    mqtt: { host: '', port: 1883, transport: 'tcp', wsPath: '/', protocol: '3.1.1', clientId: '', username: '', tls: false, tlsVerify: true, caPem: '', clientCertPem: '', topics: ['#'], includeSys: true },
    opcua: { endpoint: 'opc.tcp://', securityPolicy: 'None', securityMode: 'None', auth: 'anonymous', username: '', serverCertThumbprint: '', browseRoots: [], connector: '', publishMs: 500 },
  };
  let D = null;
  const snap = () => JSON.stringify({ kind: D.kind, name: D.name, enabled: D.enabled, settings: D.settings });
  function pendingCount() {
    if (!D) return 0;
    const a = JSON.parse(D.orig); const b = JSON.parse(snap());
    let n = 0;
    if (a.kind !== b.kind) n++;
    if (a.name !== b.name) n++;
    if (a.enabled !== b.enabled) n++;
    const keys = new Set([...Object.keys(a.settings), ...Object.keys(b.settings)]);
    keys.forEach((k) => { if (JSON.stringify(a.settings[k]) !== JSON.stringify(b.settings[k])) n++; });
    return n + Object.keys(D.secrets).length;
  }
  function confirmDiscard() {
    const n = pendingCount();
    return !n || window.confirm(`Discard ${n} unsaved ${n === 1 ? 'change' : 'changes'} to "${D.name || 'the new connection'}"?`);
  }
  async function openConnDialog(id) {
    if (D && !confirmDiscard()) return;
    let list;
    try { list = await (await fetch(`${apiBase}/api/connections`, { cache: 'no-store' })).json(); } catch { window.alert('The Witness gateway is not reachable.'); return; }
    const rec = id ? list.items.find((x) => x.id === id) : null;
    const kind = rec ? rec.kind : 'mqtt';
    const pos = D ? D.pos : null;
    D = { id, kind, meta: list.meta, name: rec ? rec.name : '', enabled: rec ? rec.enabled !== false : true,
      settings: JSON.parse(JSON.stringify(rec ? rec.settings : DLG_DEFAULTS[kind])), secrets: {}, secretsSet: rec ? rec.secretsSet || {} : {},
      errors: {}, test: null, disc: null, busy: '', tip: null, pos };
    D.orig = snap();
    renderDialog();
    const first = document.querySelector('#modal [data-f="name"]'); if (first && !id) first.focus();
  }
  function closeDialog(force) { if (!force && D && !confirmDiscard()) return; D = null; renderDialog(); }
  function dlgPayload() { return { kind: D.kind, id: D.id || undefined, name: D.name, enabled: D.enabled, settings: D.settings, secrets: D.secrets }; }
  function setField(path, value) {
    if (path === 'name' || path === 'enabled') { D[path] = value; return; }
    const [scope, key] = path.split('.');
    if (scope === 's') D.settings[key] = value;
    else if (scope === 'x') { if (value === '' || value === false) delete D.secrets[key]; else D.secrets[key] = value; }
  }
  function onDlgField(ev) {
    const el = ev.target; const path = el.dataset.f;
    let v = el.type === 'checkbox' ? el.checked : el.value;
    if (el.dataset.list) v = el.value.split('\n');
    if (el.dataset.num) v = el.value === '' ? '' : Number(el.value);
    setField(path, v);
    const key = path.split('.').pop(); if (D.errors[key]) { delete D.errors[key]; }
    if (el.dataset.rerender) renderDialog(); else updateChrome();
  }
  const plain = (html) => String(html || '').replace(/<[^>]+>/g, '');
  // one row: label | control | info. opts.wide puts the control on its own full-width line under the label.
  function fld(label, key, inner, opts = {}) {
    const info = opts.help ? `<button type="button" class="ed-info${D.tip === key ? ' on' : ''}" data-act="dlgtip" data-k="${esc(key)}" title="${esc(plain(opts.help))}" aria-label="Help for ${esc(label)}">${icon('info', 'ic-sm')}</button>` : '<span></span>';
    const lab = `<div class="ed-l${D.errors[key] ? ' has-e' : ''}"><label title="${esc(label)}">${esc(label)}</label>${opts.opt ? '<i>optional</i>' : ''}</div>`;
    const err = D.errors[key] ? `<div class="ed-e">${esc(D.errors[key])}</div>` : '';
    const tip = D.tip === key && opts.help ? `<div class="ed-tip">${opts.help}</div>` : '';
    const cls = `ed-c${D.errors[key] ? ' has-e' : ''}`;
    return opts.wide
      ? `<div class="ed-wl">${lab}${info.replace('class="ed-info', 'class="ed-info short')}</div>${tip}<div class="${cls} full">${inner}</div>${err.replace('ed-e', 'ed-e full')}`
      : `${lab}<div class="${cls}">${inner}</div>${info}${tip}${err}`;
  }
  const sec = (title) => `<div class="ed-sec">${esc(title)}</div>`;
  const full = (html) => (html ? `<div class="ed-full">${html}</div>` : '');
  const inp = (path, value, attrs = '') => `<input class="inp" data-f="${path}" value="${esc(value ?? '')}" spellcheck="false" autocomplete="off" ${attrs}>`;
  const sel = (path, value, options, attrs = '') => `<select class="inp" data-f="${path}" ${attrs}>${options.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  const chk = (path, value, label, attrs = '') => `<label class="chk"><input type="checkbox" data-f="${path}"${value ? ' checked' : ''} ${attrs}><span>${esc(label)}</span></label>`;
  const toggle = (label, key, path, value, help, attrs = '') => fld(label, key, `<label class="ed-sw"><input type="checkbox" data-f="${path}" data-rerender="1"${value ? ' checked' : ''} ${attrs.replace('data-rerender="1"', '')}><span>${value ? 'On' : 'Off'}</span></label>`, { help });
  function pemArea(path, value, placeholder) {
    return `<div class="pem"><textarea class="inp mono" rows="4" data-f="${path}" spellcheck="false" placeholder="${esc(placeholder)}">${esc(value || '')}</textarea>
      <label class="btn btn-outline pem-load">${icon('download', 'ic-sm')}Load file<input type="file" data-file="${path}" accept=".pem,.crt,.cer,.key,.txt" hidden></label></div>`;
  }
  function storageNote() {
    const st = D.meta.storage;
    return full(st.encrypted
      ? `<div class="notice ok">${icon('lock', 'ic-sm')}<span><b>Encrypted at rest.</b> ${esc(st.detail)}</span></div>`
      : `<div class="notice warn">${icon('alert', 'ic-sm')}<span><b>Passwords will be stored as plain text.</b> ${esc(st.detail)}</span></div>`);
  }
  function secretInput(path, key, label, opts = {}) {
    const isSet = D.secretsSet[key];
    const how = D.meta.storage.encrypted ? 'encrypted' : 'plain text';
    const ph = isSet ? `Stored (${how}). Blank keeps it.` : (opts.placeholder || '');
    const clearKey = `clear${key[0].toUpperCase()}${key.slice(1)}`;
    const control = opts.pem
      ? pemArea(path, D.secrets[key] || '', ph || '-----BEGIN PRIVATE KEY-----')
      : `<input class="inp" type="password" data-f="${path}" value="${esc(D.secrets[key] || '')}" placeholder="${esc(ph)}" autocomplete="new-password">`;
    return fld(label, key, control + (isSet ? chk(`x.${clearKey}`, !!D.secrets[clearKey], `Remove the stored ${opts.noun || 'password'}`) : ''), { opt: opts.opt, wide: opts.pem, help: opts.help });
  }
  function mqttForm() {
    const v = D.settings; const ws = v.transport === 'websockets';
    return `${sec('Connection')}
        ${fld('Host', 'host', inp('s.host', v.host, 'placeholder="broker.plant.local"'), { help: 'Host name or IP address of the broker, as the Witness gateway sees it.' })}
        ${fld('Port', 'port', inp('s.port', v.port, 'data-num="1" inputmode="numeric"'), { help: '1883 for MQTT, 8883 for MQTT over TLS, often 9001 or 8080 for WebSockets.' })}
        ${fld('Transport', 'transport', sel('s.transport', v.transport, [['tcp', 'MQTT (TCP)'], ['websockets', 'WebSockets']], 'data-rerender="1"'))}
        ${ws ? fld('WebSocket path', 'wsPath', inp('s.wsPath', v.wsPath, 'placeholder="/"')) : ''}
        ${fld('Protocol', 'protocol', sel('s.protocol', v.protocol, [['3.1.1', 'MQTT 3.1.1'], ['5', 'MQTT 5']]))}
        ${fld('Client ID', 'clientId', inp('s.clientId', v.clientId, 'placeholder="generated"'), { opt: true, help: 'Leave blank and Witness generates one. Two clients with the same ID disconnect each other.' })}
      ${sec('Authentication')}
        ${fld('User name', 'username', inp('s.username', v.username, 'placeholder="blank = anonymous"'), { opt: true })}
        ${secretInput('x.password', 'password', 'Password', { opt: true })}
        ${storageNote()}
      ${sec('Security')}
        ${toggle('TLS', 'tls', 's.tls', v.tls, 'Encrypt the connection. Brokers usually listen for TLS on port 8883.', 'data-rerender="1"')}
        ${v.tls ? `${toggle('Verify certificate', 'tlsVerify', 's.tlsVerify', v.tlsVerify, 'Check the broker\'s certificate and host name against the CA certificate below (or the system\'s trusted CAs).', 'data-rerender="1"')}
          ${v.tlsVerify ? '' : full(`<div class="notice warn">${icon('alert', 'ic-sm')}<span>Without verification the connection is encrypted but Witness cannot tell whether it is talking to the real broker. Use only on a lab network.</span></div>`)}
          ${fld('CA certificate', 'caPem', pemArea('s.caPem', v.caPem, '-----BEGIN CERTIFICATE-----  (blank = system CAs)'), { wide: true, opt: true, help: 'The certificate authority that signed the broker\'s certificate.' })}
          ${fld('Client certificate', 'clientCertPem', pemArea('s.clientCertPem', v.clientCertPem, '-----BEGIN CERTIFICATE-----'), { wide: true, opt: true, help: 'Only if the broker requires clients to present a certificate.' })}
          ${secretInput('x.clientKeyPem', 'clientKeyPem', 'Client private key', { pem: true, opt: true, noun: 'private key', help: 'The private key for the client certificate. Stored encrypted.' })}` : ''}
      ${sec('Topics')}
        ${fld('Subscribe to', 'topics', `<textarea class="inp mono" rows="3" data-f="s.topics" data-list="1" spellcheck="false" placeholder="#">${esc((v.topics || []).join('\n'))}</textarea>`, { wide: true, help: 'One filter per line. <code>+</code> matches one level, <code>#</code> matches everything below. Witness only reads; it never publishes.' })}
        ${toggle('$SYS statistics', 'includeSys', 's.includeSys', v.includeSys, 'Also subscribe to the broker\'s own $SYS statistics topics.')}`;
  }
  function opcuaForm() {
    const v = D.settings; const cc = D.meta.clientCert || {};
    const disc = D.disc;
    let discHtml = '';
    if (disc && disc.busy) discHtml = `<div class="notice">${icon('radio', 'ic-sm')}<span>Asking the server for its endpoints…</span></div>`;
    else if (disc && disc.error) discHtml = `<div class="notice bad">${icon('alert', 'ic-sm')}<span>${esc(disc.error)}</span></div>`;
    else if (disc && disc.endpoints) {
      const tp = disc.endpoints.map((x) => x.serverCertThumbprint).find(Boolean);
      discHtml = `<div class="eps">${disc.endpoints.map((x, i) => {
        const on = x.policy === v.securityPolicy && (x.mode === v.securityMode || (x.policy === 'None' && v.securityPolicy === 'None'));
        return `<button type="button" class="ep${on ? ' on' : ''}" data-act="dlgpickep" data-i="${i}"><b>${esc(x.policy === 'None' ? 'No security' : x.policy)}</b><span>${esc(x.policy === 'None' ? 'unencrypted' : x.mode === 'SignAndEncrypt' ? 'sign and encrypt' : 'sign only')} · ${esc(x.userTokens.join(', ') || 'no user tokens')}</span></button>`;
      }).join('')}</div>${tp ? chk('pin', v.serverCertThumbprint === tp, `Trust only this server certificate (${tp.slice(0, 12)}…)`, 'data-act-pin="' + tp + '"') : ''}`;
    }
    const none = v.securityPolicy === 'None';
    return `${sec('Connection')}
        ${fld('Endpoint URL', 'endpoint', `<div class="ed-inline">${inp('s.endpoint', v.endpoint, 'placeholder="opc.tcp://plc01.plant.local:4840"')}<button class="btn btn-outline btn-sm" data-act="dlgdiscover" title="List the server's security policies and login types">${icon('search', 'ic-sm')}Discover</button></div>`, { wide: true, help: 'The server\'s <code>opc.tcp://</code> address. <b>Discover</b> lists the security policies and login types it offers; select one to use it.' })}
        ${full(discHtml)}
      ${sec('Security')}
        ${fld('Security policy', 'securityPolicy', sel('s.securityPolicy', v.securityPolicy, (D.meta.policies || ['None']).map((x) => [x, x === 'None' ? 'None' : x]), 'data-rerender="1"'), { help: 'How messages are signed and encrypted. None sends everything, including the password, in clear text.' })}
        ${fld('Message security', 'securityMode', sel('s.securityMode', none ? 'None' : v.securityMode, none ? [['None', 'None']] : [['SignAndEncrypt', 'Sign and encrypt'], ['Sign', 'Sign only']], none ? 'disabled' : ''))}
        ${fld('Server thumbprint', 'serverCertThumbprint', inp('s.serverCertThumbprint', v.serverCertThumbprint, 'placeholder="any certificate"'), { opt: true, help: 'SHA-1 thumbprint of the server certificate to trust. When set, Witness refuses to connect if the server presents a different certificate. Blank accepts any certificate.' })}
        ${full(!none ? `<div class="notice">${icon('lock', 'ic-sm')}<span><b>Witness's client certificate</b> <code>${esc((cc.thumbprint || '').slice(0, 16))}…</code> · valid until ${esc((cc.notAfter || '').slice(0, 10))}. If the server rejects Witness, add it to the server's trusted clients. <a href="${apiBase}/api/opcua/client-cert.der" download>Download certificate</a></span></div>` : `<div class="notice warn">${icon('alert', 'ic-sm')}<span>With no security, values and the user name and password cross the network unencrypted. Choose a policy if the server offers one.</span></div>`)}
      ${sec('Authentication')}
        ${fld('Login', 'auth', sel('s.auth', v.auth, [['anonymous', 'Anonymous'], ['username', 'User and password']], 'data-rerender="1"'))}
        ${v.auth === 'username' ? `${fld('User name', 'username', inp('s.username', v.username))}${secretInput('x.password', 'password', 'Password')}${storageNote()}` : ''}
      ${sec('Browse')}
        ${fld('Branches to include', 'browseRoots', `<textarea class="inp mono" rows="2" data-f="s.browseRoots" data-list="1" spellcheck="false" placeholder="blank = everything under Objects">${esc((v.browseRoots || []).join('\n'))}</textarea>`, { wide: true, opt: true, help: 'One browse path per line, for example <code>DemoPlant/Processing</code>.' })}
        ${fld('Publishing (ms)', 'publishMs', inp('s.publishMs', v.publishMs, 'data-num="1" inputmode="numeric"'), { help: 'How often the server sends batches of value changes.' })}
        ${fld('Connect connector', 'connector', inp('s.connector', v.connector, 'placeholder="con_…"'), { opt: true, help: 'For reference: a Timebase Connect connector that reads this server live, if there is one. Handoffs do not use it: Atlas binds through the Historian connector from the Connect handoff.' })}`;
  }
  function setDialogKind(kind) {
    if (!DLG_DEFAULTS[kind] || kind === D.kind) return;
    D.kind = kind; D.settings = JSON.parse(JSON.stringify(DLG_DEFAULTS[kind])); D.secrets = {}; D.errors = {}; D.test = null; D.disc = null; D.tip = null;
    renderDialog();
  }
  // header buttons and footer pill follow the pending count without rebuilding the form (keeps focus while typing)
  function updateChrome() {
    const root = $('#modal'); if (!root || !D) return;
    const n = pendingCount(); const isNew = !D.id;
    const pill = root.querySelector('.ed-pend'); if (pill) { pill.classList.toggle('on', n > 0); pill.lastChild.textContent = `${n} pending`; }
    const save = root.querySelector('[data-act="dlgsave"]'); if (save) save.disabled = !!D.busy || (!isNew && !n);
    const disc = root.querySelector('[data-act="dlgdiscard"]'); if (disc) disc.disabled = !!D.busy || !n;
    const t = root.querySelector('.ed-title'); if (t) t.textContent = isNew ? `Add connection${D.name ? ` — ${D.name}` : ''}` : `Edit connection — ${D.name || 'Connection'}`;
  }
  function placePanel(el) {
    if (!D.pos) { el.style.left = ''; el.style.top = ''; el.style.right = ''; return; }
    const host = el.parentElement.getBoundingClientRect();
    const x = Math.max(8, Math.min(D.pos.x, host.width - el.offsetWidth - 8));
    const y = Math.max(64, Math.min(D.pos.y, host.height - 120));   // stay below the tab strip
    el.style.left = `${x}px`; el.style.top = `${y}px`; el.style.right = 'auto';
  }
  function startDrag(ev, el) {
    if (ev.button !== 0 || ev.target.closest('button, input, select, a')) return;
    ev.preventDefault();
    const host = el.parentElement.getBoundingClientRect(); const r = el.getBoundingClientRect();
    const dx = ev.clientX - r.left; const dy = ev.clientY - r.top;
    el.classList.add('dragging');
    const move = (e) => { D.pos = { x: e.clientX - host.left - dx, y: e.clientY - host.top - dy }; placePanel(el); };
    const up = () => { el.classList.remove('dragging'); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  }

  function renderDialog() {
    let root = $('#modal');
    if (!D) { if (root) root.remove(); return; }
    const host = document.querySelector('.main');
    if (!root) { root = document.createElement('div'); root.id = 'modal'; host.appendChild(root); }
    const prev = root.querySelector('.ed-body'); const scroll = prev ? prev.scrollTop : 0;
    const t = D.test;
    const testHtml = D.busy === 'test' ? `<div class="notice">${icon('radio', 'ic-sm')}<span>Testing the connection…</span></div>`
      : t ? `<div class="notice ${t.ok ? 'ok' : 'bad'}">${icon(t.ok ? 'check' : 'alert', 'ic-sm')}<span>${esc(t.message)}${t.sample && t.sample.length ? `<span class="chips" style="margin-top:6px">${t.sample.map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</span>` : ''}</span></div>` : '';
    const errCount = Object.keys(D.errors).length;
    const isNew = !D.id;
    root.innerHTML = `<div class="ed" role="dialog" aria-label="${isNew ? 'Add connection' : 'Edit connection'}">
      <div class="ed-h" title="Drag to move">
        <span class="ed-grip" aria-hidden="true"><span></span><span></span><span></span></span>
        <div class="ed-title"></div>
        <div class="ed-acts">
          <button class="ed-btn ghost" data-act="dlgdiscard">Discard</button>
          <button class="ed-btn primary" data-act="dlgsave">${D.busy === 'save' ? 'Saving…' : isNew ? 'Add' : 'Save'}</button>
        </div>
        <button class="ed-x" data-act="dlgclose" aria-label="Close" title="Close (Esc)">${icon('x', 'ic')}</button>
      </div>
      <div class="ed-body"><div class="ed-grid">
        ${fld('Type', 'kind', `<select class="inp" id="dlgKind"${D.id ? ' disabled title="The type of a saved connection cannot be changed"' : ''}>${[['mqtt', 'MQTT broker'], ['opcua', 'OPC UA server']].map(([k, l]) => `<option value="${k}"${D.kind === k ? ' selected' : ''}>${l}</option>`).join('')}</select>`, { help: D.id ? 'The type of a saved connection cannot be changed. Delete it and add a new one instead.' : 'An MQTT broker, or an OPC UA server.' })}
        ${fld('Name', 'name', inp('name', D.name, `placeholder="${D.kind === 'mqtt' ? 'plant-broker' : 'line-1-plc'}"`), { help: 'Shown in Connections, on the connection\'s tab, and as the top branch of its tree.' })}
        ${toggle('Connected', 'enabled', 'enabled', D.enabled, 'Turn off to pause the connection without deleting it.', 'data-rerender="1"')}
        ${D.kind === 'mqtt' ? mqttForm() : opcuaForm()}
        ${full(testHtml)}
        ${full(errCount ? `<div class="notice bad">${icon('alert', 'ic-sm')}<span>Fix the ${errCount === 1 ? 'highlighted field' : `${errCount} highlighted fields`} before saving.</span></div>` : '')}
      </div></div>
      <div class="ed-f">
        <span class="ed-pend"><span class="ed-dot"></span><span>0 pending</span></span>
        <span class="ed-f-acts">
          <button class="ed-btn outline" data-act="dlgtest"${D.busy ? ' disabled' : ''}>${icon('plug', 'ic-sm')}${D.busy === 'test' ? 'Testing…' : 'Test'}</button>
          ${D.id ? `<button class="ed-btn outline danger" data-act="dlgdelete">${icon('trash', 'ic-sm')}Delete</button>` : ''}
        </span>
      </div></div>`;
    const panel = root.querySelector('.ed');
    placePanel(panel);
    root.querySelector('.ed-h').addEventListener('pointerdown', (e) => startDrag(e, panel));
    const kindSel = root.querySelector('#dlgKind');
    if (kindSel && !D.id) kindSel.addEventListener('change', () => setDialogKind(kindSel.value));
    root.querySelectorAll('[data-f]').forEach((el) => {
      el.addEventListener(el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input', onDlgField);
    });
    root.querySelectorAll('[data-file]').forEach((el) => el.addEventListener('change', async () => {
      const f = el.files && el.files[0]; if (!f) return;
      setField(el.dataset.file, (await f.text()).trim()); renderDialog();
    }));
    const pin = root.querySelector('[data-act-pin]');
    if (pin) pin.addEventListener('change', () => { D.settings.serverCertThumbprint = pin.checked ? pin.dataset.actPin : ''; renderDialog(); });
    root.querySelector('.ed-body').scrollTop = scroll;
    updateChrome();
  }
  async function dialogAction(act, el) {
    if (!D) return;
    if (act === 'dlgclose') { closeDialog(); return; }
    if (act === 'dlgtip') { D.tip = D.tip === el.dataset.k ? null : el.dataset.k; renderDialog(); return; }
    if (act === 'dlgdiscard') {
      const o = JSON.parse(D.orig);
      D.kind = o.kind; D.name = o.name; D.enabled = o.enabled; D.settings = o.settings; D.secrets = {}; D.errors = {}; D.test = null;
      renderDialog(); return;
    }
    if (act === 'dlgpickep') {
      const x = D.disc.endpoints[Number(el.dataset.i)];
      D.settings.securityPolicy = x.policy; D.settings.securityMode = x.policy === 'None' ? 'None' : x.mode;
      if (x.userTokens.includes('UserName') && !x.userTokens.includes('Anonymous')) D.settings.auth = 'username';
      renderDialog(); return;
    }
    if (act === 'dlgdiscover') {
      D.disc = { busy: true }; renderDialog();
      try {
        const r = await (await fetch(`${apiBase}/api/connections/discover`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: D.settings.endpoint }) })).json();
        D.disc = r.errors ? { error: Object.values(r.errors)[0] } : r.error ? { error: r.error } : { endpoints: r.endpoints };
      } catch { D.disc = { error: 'The Witness gateway is not reachable.' }; }
      renderDialog(); return;
    }
    if (act === 'dlgtest') {
      D.busy = 'test'; D.test = null; renderDialog();
      try {
        const res = await fetch(`${apiBase}/api/connections/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(dlgPayload()) });
        const r = await res.json();
        if (r.errors) { D.errors = r.errors; D.test = null; } else D.test = r;
      } catch { D.test = { ok: false, message: 'The Witness gateway is not reachable.' }; }
      D.busy = ''; renderDialog(); return;
    }
    if (act === 'dlgsave') {
      D.busy = 'save'; renderDialog();
      try {
        const res = await fetch(D.id ? `${apiBase}/api/connections/${encodeURIComponent(D.id)}` : `${apiBase}/api/connections`, { method: D.id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(dlgPayload()) });
        const r = await res.json();
        if (!res.ok) { D.errors = r.errors || { name: 'The gateway refused the change.' }; D.busy = ''; renderDialog(); return; }
        S.openConn.add(`${r.kind === 'mqtt' ? 'mqtt' : 'ua'}:${r.id}`);
        closeDialog(true);
      } catch { D.busy = ''; D.test = { ok: false, message: 'The Witness gateway is not reachable.' }; renderDialog(); }
      return;
    }
    if (act === 'dlgdelete') {
      if (!window.confirm(`Delete the connection "${D.name}"?\n\nWitness disconnects from it and forgets its settings and stored credentials. This cannot be undone.`)) return;
      try { await fetch(`${apiBase}/api/connections/${encodeURIComponent(D.id)}`, { method: 'DELETE' }); } catch { /* the list refresh shows the result */ }
      closeDialog(true);
    }
  }

  // ---------------------------------------------------------------- pages
  function buildPage() {
    const page = $('#page');
    const v = vinfo(S.view);
    const titleRow = (count) => `<div class="title-row"><h1>${esc(v.title)}</h1>${count !== undefined ? `<span class="count" id="titleCount">${esc(count)}</span>` : ''}</div>`;
    if (isConnView(S.view)) {
      const c = cur(); const k = v.conn; const ua = c.key === 'ua'; const L = lensOf(S.view);
      const st = k ? (ua ? uaState(k.s) : k.b.conn) : 'connecting';
      const addr = k ? (ua ? k.s.status.endpoint : k.b.url) : '';
      const desc = ua
        ? 'Every object and variable on this OPC UA server, subscribed live through the Witness gateway. Select a node to see its current value.'
        : 'Every topic on this broker, updating live. Select a branch or topic to see its current state.';
      page.innerHTML = `<header class="page-head"><div><div class="title-row"><span class="dot ${dotFor(st)}" id="connDot" title="${esc(humanize(st || ''))}"></span><h1>${esc(v.title)}</h1><span class="count" id="titleCount">${esc(fmtNum(connCount(k)))}</span><span class="acc-type">${ua ? 'OPC UA server' : 'MQTT broker'}${k ? secureBadge(ua ? { s: k.s } : { b: k.b }) : ''}</span></div>
          <p>${addr ? `<code class="addr">${esc(addr)}</code> · ` : ''}${desc}</p></div><div class="stats" id="hdrStats">${statsHtml()}</div></header>
        <div class="toolbar">
          <label class="search">${icon('search', 'ic-sm')}<input id="filter" type="search" placeholder="${ua ? 'Filter nodes...' : 'Filter topics...'}" autocomplete="off" spellcheck="false" value="${esc(c.filter)}"></label>
          ${ua ? '' : `<label class="check"><input type="checkbox" id="showSys"${c.showSys ? ' checked' : ''}> Show $SYS topics</label>`}
          <span class="spacer"></span>
          <button class="btn btn-outline" data-act="expandAll">${icon('expand', 'ic-sm')}Expand all</button>
          <button class="btn btn-outline" data-act="collapseAll">${icon('collapse', 'ic-sm')}Collapse all</button>
          <button class="btn ${L.live ? 'btn-primary' : 'btn-outline'}" data-act="livetoggle" id="liveBtn" title="${L.live ? 'Close' : 'Open'} the Live messages window">${icon('activity', 'ic-sm')}Live messages</button>
        </div>
        <div class="conn-work${L.live ? ' with-live' : ''}">
          <div class="split${L.wide ? ' tree-wide' : ''}">
            <div class="panel tree-panel"><div class="panel-h"><span class="lbl">${ua ? 'Address space' : 'Namespace'}</span><span class="spacer"></span>
              <button class="icon-btn wide-btn" data-act="treewide" title="${L.wide ? 'Restore the namespace browser (Esc)' : 'Expand the namespace browser'}" aria-pressed="${L.wide}">${icon(L.wide ? 'minimize' : 'maximize', 'ic-sm')}</button></div>
              <div class="tree" id="tree" role="tree"></div></div>
            <div class="detail" id="detail"></div></div>
          ${L.live ? `<section class="live-dock" aria-label="Live messages">
            <div class="live-dock-h">${icon('activity', 'ic-sm')}<span class="lbl">Live messages</span><span class="note" id="liveNote"></span><span class="spacer"></span>
              <button class="icon-btn" data-act="livetoggle" title="Close Live messages">${icon('x', 'ic-sm')}</button></div>
            <div class="list live-list" id="liveList"></div></section>` : ''}
        </div>`;
      $('#filter').addEventListener('input', (e) => { const k = cur(); k.filter = e.target.value; k.treeDirty = true; frame(true); });
      const sys = $('#showSys');
      if (sys) sys.addEventListener('change', (e) => { const k = cur(); k.showSys = e.target.checked; k.treeDirty = true; k.viewDirty = true; frame(true); });
      c.treeDirty = true; c.viewDirty = true; c.viewKey = null; lastFeed = -1;
    } else if (S.view === 'atlas') {
      buildAtlasPage(page, titleRow);
    } else {
      page.innerHTML = `<header class="page-head"><div>${titleRow(fmtNum(BROKERS.length + SERVERS.size))}<p>Every MQTT broker and OPC UA server Witness is subscribed to. Select one to browse its namespace in a new tab, expand it with the arrow to see its settings and live status, or edit it with the pencil.</p></div><div class="stats" id="hdrStats">${statsHtml()}</div></header>
        <div class="toolbar"><label class="search">${icon('search', 'ic-sm')}<input id="connFilter" type="search" placeholder="Filter connections..." autocomplete="off" spellcheck="false" value="${esc(S.connFilter)}"></label>
          <span class="spacer"></span><button class="btn btn-primary" data-act="connadd">${icon('plus', 'ic-sm')}Add connection</button></div>
        <div class="conn-scroll" id="connList"></div>`;
      $('#connFilter').addEventListener('input', (e) => { S.connFilter = e.target.value; renderConnections(); });
      renderConnections();
    }
  }
  function renderLive() {
    const el = $('#liveList'); const k = connOf(S.view); if (!el || !k) return;
    const all = feedItems(k.id);
    const f = cur().filter.trim().toLowerCase();
    const items = (f ? all.filter((m) => m.topic.toLowerCase().includes(f)) : all).slice(0, 200);
    const cut = k.name.length + 1;
    el.innerHTML = items.length
      ? items.map((m) => `<div class="li click msg-li${m.id > S.feedSeen ? ' new' : ''}" data-act="open" data-path="${esc(m.topic)}"><span class="t">${fmtTime(m.t, true)}</span><span class="tp" title="${esc(m.topic.slice(cut))}">${esc(m.topic.slice(cut))}</span><span class="p">${esc(oneLine(m.text, 260) || '(empty)')}</span><button class="icon-sm row-cp" data-act="fmenu" data-id="${m.id}" title="Copy options">${icon('copy', 'ic-sm')}</button></div>`).join('')
      : `<div class="empty-state small">${icon('activity')}<h2>${f ? 'No recent messages match the filter' : 'No messages yet'}</h2><p>${k.kind === 'ua' ? 'Value changes' : 'Messages'} appear here as they arrive, newest first. Select one to open it.</p></div>`;
    const note = $('#liveNote'); if (note) note.textContent = `${fmtNum(items.length)} most recent${f ? ' matching the filter' : ''} · newest first`;
    S.feedSeen = S.feedId;
  }

  // ---------------------------------------------------------------- Handoffs (agent run in the gateway)
  function mdInline(t) {
    return esc(t)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>');
  }
  function mdToHtml(md) {
    const lines = md.replace(/\r/g, '').split('\n');
    const out = []; let i = 0;
    const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
    while (i < lines.length) {
      const l = lines[i];
      if (/^```/.test(l)) {
        const buf = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++; out.push(`<pre class="json">${esc(buf.join('\n'))}</pre>`); continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) { out.push(`<h${h[1].length + 1} class="md-h${h[1].length}">${mdInline(h[2])}</h${h[1].length + 1}>`); i++; continue; }
      if (/^>\s?/.test(l)) {
        const buf = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
        out.push(`<blockquote>${buf.map(mdInline).join('<br>')}</blockquote>`); continue;
      }
      if (isRow(l)) {
        const rows = [];
        while (i < lines.length && isRow(lines[i])) rows.push(lines[i++]);
        const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
        const [head, ...rest] = body;
        out.push(`<div class="md-table"><table><thead><tr>${cells(head).map((c) => `<th>${mdInline(c)}</th>`).join('')}</tr></thead><tbody>${rest.map((r) => `<tr>${cells(r).map((c) => `<td>${mdInline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
        continue;
      }
      if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
        const ordered = /^\s*\d+\./.test(l); const buf = [];
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) buf.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''));
        out.push(`<${ordered ? 'ol' : 'ul'}>${buf.map((b) => `<li>${mdInline(b)}</li>`).join('')}</${ordered ? 'ol' : 'ul'}>`); continue;
      }
      if (!l.trim()) { i++; continue; }
      const buf = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|>|```|\s*\||\s*([-*]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
      if (!buf.length) { buf.push(lines[i++]); }
      out.push(`<p>${mdInline(buf.join(' '))}</p>`);
    }
    return out.join('');
  }
  async function loadAgentInfo() {
    try { S.agent.info = await (await fetch(`${apiBase}/api/agent/info`, { cache: 'no-store' })).json(); } catch { S.agent.info = null; }
    S.agent.dirty = true;
  }
  async function loadLatestBrief(file) {
    const A = S.agent;
    if (!A.server || A.running) return;
    try {
      const q = `server=${encodeURIComponent(A.server)}${file ? `&file=${encodeURIComponent(file)}` : ''}`;
      const r = await (await fetch(`${apiBase}/api/agent/latest?${q}`, { cache: 'no-store' })).json();
      A.versions = r.versions || [];
      if (r.brief && !A.running && (file || !A.brief)) {
        A.brief = r.brief; A.collector = r.collector || ''; A.connect = r.connect || ''; A.artifact = r.artifact; A.domain = r.domain || A.domain;
        if (!file) A.items = [{ kind: 'status', text: `Showing saved handoffs v${r.artifact.version} for ${r.artifact.domain}, drafted ${ago(Date.parse(r.artifact.createdAt))}.` }];
        A.dirty = true; buildPage();
      } else { A.dirty = true; }
    } catch { /* gateway unreachable */ }
  }
  function gagePrompt(a) {
    return `Build the Atlas domain described in the Witness brief at ${a.url}

Fetch it with Bash (the Atlas container has no curl):
python3 -c "import urllib.request; print(urllib.request.urlopen('${a.url}').read().decode())"

Then follow the instructions at the top of the brief: run the model-domain skill in Build mode for the domain \`${a.domain}\`, treat the Domain Summary as the confirmed interview output, and use its Source Bindings for the mapper step. Show me the architect plan before anything is built.`;
  }
  function connectPrompt() {
    const body = S.agent.connect.replace(/^---\n[\s\S]*?\n---\n/, '').trim();
    return `Set up the Timebase Connect Historian connector described in this Witness handoff, so Atlas can read the historized data. Show me the settings before you start the connector, and tell me the connector id when it is running.\n\n${body}`;
  }
  function collectorPrompt() {
    const body = S.agent.collector.replace(/^---\n[\s\S]*?\n---\n/, '').trim();
    return `Create the Timebase Collector logging instance described in this Witness handoff. Show me the settings and the historian link before you start the collector.\n\n${body}`;
  }
  const BRIEF_URL = (f, dl) => `${apiBase}/briefs/${encodeURIComponent(f)}${dl ? '?download=1' : ''}`;
  function dlBtn(file, label, title) {
    return file ? `<a class="dl-btn" href="${BRIEF_URL(file, true)}" download="${esc(file)}" title="${esc(title)}">${icon('download', 'ic-sm')}<span>${esc(label)}</span></a>`
      : `<span class="dl-btn disabled" title="Not available">${icon('download', 'ic-sm')}<span>${esc(label)}</span></span>`;
  }
  function agentItem(ev) {
    const A = S.agent; const items = A.items; const lastIt = items[items.length - 1];
    if (ev.type === 'status') items.push({ kind: 'status', text: ev.text });
    else if (ev.type === 'thinking_start') items.push({ kind: 'thinking', text: '' });
    else if (ev.type === 'thinking') { if (lastIt && lastIt.kind === 'thinking') lastIt.text += ev.delta; else items.push({ kind: 'thinking', text: ev.delta }); }
    else if (ev.type === 'tool') items.push({ kind: 'tool', name: ev.name, input: ev.input, result: null });
    else if (ev.type === 'tool_result') { const t = [...items].reverse().find((x) => x.kind === 'tool' && x.name === ev.name && x.result === null); if (t) { t.result = ev.summary; t.error = ev.error; } }
    else if (ev.type === 'text') { A.draft += ev.delta; if (!lastIt || lastIt.kind !== 'writing') items.push({ kind: 'writing' }); }
    else if (ev.type === 'done') { A.brief = ev.brief; A.artifact = ev.artifact || null; A.draft = ''; A.usage = ev.usage; A.running = false; if (ev.artifact) { items.push({ kind: 'saved', text: `Saved Atlas handoff ${ev.artifact.file}${ev.artifact.collector ? ` and Collector handoff ${ev.artifact.collector.file}` : ''}` }); setTimeout(() => loadLatestBrief(ev.artifact.file), 50); } items.push({ kind: 'done', text: `Handoffs ready after ${ev.turns} model turns · ${fmtNum((ev.usage.input || 0) + (ev.usage.cacheWrite || 0) + (ev.usage.cacheRead || 0))} input / ${fmtNum(ev.usage.output)} output tokens${ev.usage.cacheRead ? ` · ${fmtNum(ev.usage.cacheRead)} read from cache` : ''}` }); }
    else if (ev.type === 'error') { A.error = ev.message; A.running = false; items.push({ kind: 'error', text: ev.message }); }
    A.dirty = true;
  }
  function selectAgentServer(id) {
    if (S.agent.running) return;
    S.agent.server = id; S.agent.domain = ''; S.agent.brief = ''; S.agent.collector = ''; S.agent.connect = ''; S.agent.artifact = null; S.agent.items = []; S.agent.error = null; S.agent.dirty = true;
    buildPage(); loadLatestBrief();
  }

  async function startMapping() {
    const A = S.agent;
    if (A.running || !A.server) return;
    const dom = ($('#agentDomain') && $('#agentDomain').value.trim()) || A.domain;
    A.items = []; A.brief = ''; A.collector = ''; A.connect = ''; A.handoff = 'atlas'; A.draft = ''; A.error = null; A.usage = null; A.artifact = null; A.running = true; A.dirty = true;
    renderAtlas();
    try {
      const res = await fetch(`${apiBase}/api/agent/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ server: A.server, domain: dom }) });
      const r = await res.json();
      if (!res.ok) { agentItem({ type: 'error', message: r.error || `Gateway returned ${res.status}` }); return; }
      A.domain = r.domain;
      if (A.es) A.es.close();
      A.es = new EventSource(`${apiBase}/api/agent/runs/${r.run}/events`);
      A.es.onmessage = (e) => { try { agentItem(JSON.parse(e.data)); } catch { /* ignore */ } };
      A.es.addEventListener('end', () => { A.es.close(); A.es = null; if (A.running) { A.running = false; A.dirty = true; } });
      A.es.onerror = () => { if (A.es && A.es.readyState === 2) { A.es = null; if (A.running) agentItem({ type: 'error', message: 'Lost the connection to the gateway during the run.' }); } };
    } catch (err) {
      agentItem({ type: 'error', message: `Could not reach the Witness gateway (${err.message}).` });
    }
  }
  function buildAtlasPage(page, titleRow) {
    const A = S.agent;
    const servers = [...SERVERS.values()];
    if (!A.server && servers.length) A.server = servers[0].id;
    const sel = SERVERS.get(A.server);
    if (!A.domain && sel) A.domain = `${sel.name}`.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const info = A.info || {};
    page.innerHTML = `<header class="page-head"><div>${titleRow()}<p>An agent studies a server's namespace and plans its move into Timebase: a Collector instance that logs it to Historian, and an Atlas domain that Gage can build with types, hierarchy, instances and live bindings.</p></div>
        <div class="stats">${stat('Model', info.model || '—')}${stat('Effort', info.effort || '—')}${stat('API key', info.keyConfigured === undefined ? '—' : info.keyConfigured ? 'Configured' : 'Missing')}</div></header>
      <div class="toolbar">
        <label class="pick"><span class="dot ${sel ? dotFor(uaState(sel)) : ''}" id="agentSrcDot"></span><select class="inp" id="agentSrc" title="Namespace to map">${servers.length ? '' : '<option value="">No OPC UA servers</option>'}<optgroup label="OPC UA servers">${servers.map((s) => `<option value="${esc(s.id)}"${s.id === A.server ? ' selected' : ''}>${esc(s.name)}</option>`).join('')}</optgroup>${BROKERS.length ? `<optgroup label="MQTT brokers (not yet supported)">${BROKERS.map((b) => `<option disabled>${esc(b.name)}</option>`).join('')}</optgroup>` : ''}</select></label>
        <label class="search" style="width:240px"><span class="ic-sm" style="left:12px;top:50%;transform:translateY(-50%);position:absolute;font:11px 'JetBrains Mono',monospace;color:var(--muted-fg)">domain</span><input id="agentDomain" value="${esc(A.domain)}" style="padding-left:64px" spellcheck="false"></label>
        <span class="spacer"></span>
        <button class="btn btn-primary" data-act="agentrun" id="agentRun">${icon('sparkles', 'ic-sm')}Plan the move</button>
      </div>
      <div class="agent-split">
        <div class="panel agent-log"><div class="agent-h"><span class="lbl">Agent activity</span><span class="note" id="agentState"></span></div><div id="agentLog"></div></div>
        <div class="panel agent-brief"><div class="ho-bar">
            <div class="handoffs" id="agentHandoffs"></div>
            <div class="ho-ver"><span class="lbl">Version</span><select id="agentVersion" class="ver-select" title="Saved versions"></select></div></div>
          <div class="md" id="agentBrief"></div></div>
      </div>`;
    const d = $('#agentDomain'); d.addEventListener('input', () => { A.domain = d.value; });
    const src = $('#agentSrc'); src.addEventListener('change', () => { if (src.value && src.value !== A.server) selectAgentServer(src.value); });
    const v = $('#agentVersion'); v.addEventListener('change', () => { if (v.value) loadLatestBrief(v.value); });
    A.dirty = true; renderAtlas();
    if (!A.info) loadAgentInfo();
    if (!A.brief && !A.running) loadLatestBrief();
  }
  function renderAtlas() {
    const A = S.agent;
    const log = $('#agentLog'); const brief = $('#agentBrief'); if (!log || !brief) return;
    const srcSel = $('#agentSrc'); if (srcSel) srcSel.disabled = A.running;
    const runBtn = $('#agentRun');
    if (runBtn) { runBtn.disabled = A.running || !A.server; runBtn.innerHTML = A.running ? `${icon('sparkles', 'ic-sm')}Planning…` : `${icon('sparkles', 'ic-sm')}${A.brief ? 'Plan again' : 'Plan the move'}`; }
    const st = $('#agentState'); if (st) st.textContent = A.running ? 'Running' : A.error ? 'Stopped' : A.brief ? 'Done' : '';
    const art = A.artifact;
    const vs = $('#agentVersion');
    if (vs) {
      const opts = A.versions.map((e) => `<option value="${esc(e.file)}"${art && art.file === e.file ? ' selected' : ''}>${esc(e.domain)} v${e.version} · ${esc(new Date(Date.parse(e.createdAt)).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }))}</option>`).join('');
      if (vs.dataset.sig !== opts) { vs.innerHTML = opts || '<option value="">No saved versions</option>'; vs.dataset.sig = opts; }
      vs.disabled = A.running || !A.versions.length;
    }
    const ho = $('#agentHandoffs');
    if (ho) {
      const ready = art && !A.running;
      const col = ready ? art.collector : null;
      const con = ready ? art.connect : null;
      const sig = JSON.stringify([ready && art.file, col && col.file, con && con.file, A.handoff]);
      if (ho.dataset.sig !== sig) {
        ho.dataset.sig = sig;
        const card = (key, ic, title, sub, meta, acts) => `<div class="handoff${A.handoff === key ? ' on' : ''}" data-act="agentho" data-h="${key}" role="button" tabindex="0" aria-pressed="${A.handoff === key}" title="Show the ${title} handoff">
            <div class="ho-top"><span class="ho-ic">${icon(ic, 'ic-sm')}</span><div class="ho-t"><b>${title}</b><span>${sub}</span></div></div>
            <div class="ho-meta">${meta}</div>
            ${acts ? `<div class="ho-acts">${acts}</div>` : ''}</div>`;
        const acts = (act, dls) => `<button class="btn btn-outline btn-sm" data-act="${act}">${icon('copy', 'ic-sm')}Copy Gage prompt</button><div class="ho-dl">${dls}</div>`;
        const missing = 'Not in this version. Select Plan again to add it.';
        ho.innerHTML = ready ? `
          ${card('collector', 'database', 'Collector', 'Logs the server to Historian', col ? `Instance <code>${esc(col.name)}</code> → dataset <code>${esc(col.dataset)}</code> · ${fmtNum(col.variablesLogged)} tags` : missing,
            col ? acts('agentcolprompt', dlBtn(col.file, '.md', 'Download the Collector handoff') + dlBtn(col.json, '.json', 'Download the Collector settings')) : '')}
          ${card('connect', 'plug', 'Connect', 'Serves the dataset to Atlas', con ? `Historian connector · dataset <code>${esc(con.dataset)}</code> · ${fmtNum(con.tagCount)} tags` : missing,
            con ? acts('agentconprompt', dlBtn(con.file, '.md', 'Download the Connect handoff') + dlBtn(con.json, '.json', 'Download the Connect settings')) : '')}
          ${card('atlas', 'sparkles', 'Atlas', 'Gage builds the domain', `Domain <code>${esc(art.domain)}</code>${con ? ` · bindings through the Connect handoff` : ''} · Gage fetches <code>${esc(art.url)}</code>`,
            acts('agentprompt', dlBtn(art.file, '.md', 'Download the Atlas handoff')))}` : '';
      }
    }
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
    log.innerHTML = A.items.length ? A.items.map((it) => {
      if (it.kind === 'status') return `<div class="ag-row">${icon('radio', 'ic-sm')}<span>${esc(it.text)}</span></div>`;
      if (it.kind === 'thinking') return it.text ? `<div class="ag-row ag-think">${icon('brain', 'ic-sm')}<span>${esc(it.text)}</span></div>` : '';
      if (it.kind === 'tool') {
        const arg = it.input && it.input.path ? ` <code>${esc(it.input.path)}</code>` : '';
        return `<div class="ag-row ag-tool${it.error ? ' err' : ''}">${icon('wrench', 'ic-sm')}<span><b>${esc(it.name)}</b>${arg}${it.result ? `<em>${esc(it.result)}</em>` : '<em>running…</em>'}</span></div>`;
      }
      if (it.kind === 'writing') return `<div class="ag-row">${icon('sparkles', 'ic-sm')}<span>Writing the Atlas brief${A.running ? '…' : ''}</span></div>`;
      if (it.kind === 'saved') return `<div class="ag-row ag-done">${icon('download', 'ic-sm')}<span>${esc(it.text)}</span></div>`;
      if (it.kind === 'done') return `<div class="ag-row ag-done">${icon('check', 'ic-sm')}<span>${esc(it.text)}</span></div>`;
      if (it.kind === 'error') return `<div class="ag-row ag-err">${icon('x', 'ic-sm')}<span>${esc(it.text)}</span></div>`;
      return '';
    }).join('') : `<div class="tree-empty">${SERVERS.size ? 'Pick a server, name the domain, then select Plan the move. The agent reads the namespace through the Witness gateway and never writes to it, to Collector or to Atlas.' : 'No OPC UA servers are connected to the gateway.'}</div>`;
    if (nearBottom || A.running) log.scrollTop = log.scrollHeight;
    const showCol = A.handoff !== 'atlas' && !A.running;
    const src = !showCol ? (A.brief || A.draft) : A.handoff === 'connect' ? A.connect : A.collector;
    const text = (src || '').replace(/^---\n[\s\S]*?\n---\n/, ''); // front matter is summarised in the handoff cards
    const sig = `${A.handoff}|${A.running}|${text.length}|${art && art.file}`;
    if (brief.dataset.sig !== sig) {
      brief.dataset.sig = sig;
      brief.innerHTML = text ? mdToHtml(text) : showCol
        ? `<div class="empty-state">${icon(A.handoff === 'connect' ? 'plug' : 'database')}<h2>No ${A.handoff === 'connect' ? 'Connect' : 'Collector'} handoff</h2><p>This version was planned before Witness produced ${A.handoff === 'connect' ? 'Connect' : 'Collector'} handoffs. Select Plan again to create one.</p></div>`
        : `<div class="empty-state">${icon('sparkles')}<h2>No plan yet</h2><p>The handoffs appear here as the agent writes them. Review them, then pass each one to Gage in Collector, Connect and Atlas, in that order.</p></div>`;
    }
    if (A.draft && !A.brief) brief.scrollTop = brief.scrollHeight;
  }

  // ---------------------------------------------------------------- shell
  function renderNav() {
    const item = (v) => `<button class="nav-item${S.view === v ? ' on' : ''}" data-act="nav" data-view="${v}" title="${VIEWS[v].title}">${icon(VIEWS[v].icon)}<span>${VIEWS[v].label}</span></button>`;
    $('#sideNav').innerHTML = `${item('conn')}<div class="nav-sec">Build</div>${item('atlas')}`;
  }
  function renderTabs() {
    $('#tabs').innerHTML = S.tabs.filter(vinfo).map((v) => { const i = vinfo(v); return `<div class="tab${S.view === v ? ' on' : ''}" data-act="nav" data-view="${esc(v)}" title="${esc(i.title)}">${icon(i.icon, 'ic-sm')}<span class="tab-label">${esc(i.label)}</span><button class="icon-sm" data-act="close" data-view="${esc(v)}" title="Close tab">${icon('x', 'ic-sm')}</button></div>`; }).join('');
  }
  // a connection tab's selection is kept as a path inside the connection, so a rename keeps it
  function saveLens() {
    const k = connOf(S.view); if (!k) return;
    const L = lensOf(S.view); const c = cur();
    if (!L.bound) return;
    L.local = c.selected === k.name ? '' : c.selected.startsWith(`${k.name}/`) ? c.selected.slice(k.name.length + 1) : L.local;
    L.filter = c.filter; L.showSys = c.showSys; L.tab = c.tab;
  }
  function loadLens(view) {
    const k = connOf(view); if (!k) return;
    const L = lensOf(view); const c = ctxOf(view);
    c.selected = L.local ? `${k.name}/${L.local}` : k.name;
    for (let n = find(c, c.selected); n && n.parent; n = n.parent) c.expanded.add(n.parent.path);
    c.filter = L.filter; c.showSys = L.showSys; c.tab = L.tab;
    c.treeDirty = true; c.viewDirty = true; c.viewKey = null;
    L.bound = true;
  }
  function go(view, sync = true) {
    if (!vinfo(view)) view = 'conn';
    saveLens();
    if (!S.tabs.includes(view)) S.tabs.push(view);
    S.view = view;
    loadLens(view);
    renderNav(); renderTabs(); buildPage(); frame(true);
    if (sync) syncHash();
  }
  function syncHash() {
    let h = `#/${S.view}`;
    const k = connOf(S.view);
    if (isConnView(S.view)) {
      const id = S.view.slice(2);
      const c = cur();
      const local = k && c.selected.startsWith(`${k.name}/`) ? c.selected.slice(k.name.length + 1) : (k ? '' : lensOf(S.view).local);
      h = `#/c/${encodeURIComponent(id)}${local ? `/${local.split('/').map(encodeURIComponent).join('/')}` : ''}`;
    }
    if (location.hash !== h) history.replaceState(null, '', h);
  }

  let lastFeed = -1;
  function frame(force) {
    if (S.paused && !force) return;
    if (isConnView(S.view)) {
      const c = cur();
      if (c.treeDirty) { renderTree(); c.treeDirty = false; }
      if (c.viewDirty || c.viewKey !== c.selected) { renderDetail(); c.viewDirty = false; c.viewKey = c.selected; }
      if (lensOf(S.view).live && S.feedId !== lastFeed) { renderLive(); lastFeed = S.feedId; }
      const k = connOf(S.view); const dot = $('#connDot');
      if (k && dot) dot.className = `dot ${dotFor(k.kind === 'ua' ? uaState(k.s) : k.b.conn)}`;
    } else if (S.view === 'atlas') {
      if (S.agent.dirty) { renderAtlas(); S.agent.dirty = false; }
    }
    const hs = $('#hdrStats'); if (hs) hs.innerHTML = statsHtml();
    const tc = $('#titleCount');
    if (tc && S.view !== 'atlas') tc.textContent = fmtNum(S.view === 'conn' ? BROKERS.length + SERVERS.size : connCount(connOf(S.view)));
  }
  setInterval(frame, 250);
  setInterval(() => {
    for (const c of Object.values(CTX)) { c.rateHist.push(c.tick); c.tick = 0; if (c.rateHist.length > 60) c.rateHist.shift(); }
    for (const b of BROKERS) {
      const sys = (k) => parseFloat(b.sys[k]);
      pushHist(b.hist.rate, b.tick); b.tick = 0;
      pushHist(b.hist.recv, sys('broker/load/messages/received/1min'));
      pushHist(b.hist.sent, sys('broker/load/messages/sent/1min'));
      pushHist(b.hist.clients, sys('broker/clients/connected'));
      pushHist(b.hist.retained, sys('broker/retained messages/count'));
      pushHist(b.hist.bytesIn, sys('broker/load/bytes/received/1min'));
    }
    for (const s of SERVERS.values()) {
      pushHist(s.hist.rate, s.tick); s.tick = 0;
      const vars = [...s.index.values()].filter((n) => n.uaVar);
      pushHist(s.hist.vars, vars.length);
      pushHist(s.hist.good, vars.length ? (vars.filter((n) => n.quality === 'good').length / vars.length) * 100 : NaN);
    }
    if (!S.paused) {
      document.querySelectorAll('[data-ago]').forEach((el) => { el.textContent = ago(Number(el.dataset.ago)); });
      cur().treeDirty = true;
      if (S.view === 'conn') renderConnections();
    }
  }, 1000);

  // ---------------------------------------------------------------- interaction
  function select(path) {
    if (!isConnView(S.view)) return;
    const c = cur(); const top = scopeTop();
    if (top && path !== top.path && !path.startsWith(`${top.path}/`)) path = top.path;
    c.selected = path;
    for (let n = find(c, path); n && n.parent; n = n.parent) c.expanded.add(n.parent.path);
    c.treeDirty = true; c.viewDirty = true;
    frame(true); syncHash();
    const row = document.querySelector('.row.sel');
    if (row) row.scrollIntoView({ block: 'nearest' });
    const d = $('#detail'); if (d) d.scrollTop = 0;
  }
  function fromHash() {
    const parts = location.hash.replace(/^#\/?/, '').split('/').filter((x, i) => i > 0 || x !== '');
    if (!parts.length) return { view: 'conn', path: '' };
    if (parts[0] === 'c' && parts[1]) return { view: `c:${decodeURIComponent(parts[1])}`, path: parts.slice(2).map(decodeURIComponent).join('/') };
    if (parts[0] === 'broker' || parts[0] === 'live') return { view: 'conn', path: '' };
    if (VIEWS[parts[0]]) return { view: parts[0], path: '' };
    // links from before connection tabs: #/ns/<broker>/<topic>, #/ua/<server>/<node>, or a bare topic path
    const legacy = parts[0] === 'ua' || parts[0] === 'ns' ? parts.slice(1) : parts;
    return { view: 'conn', path: '', legacy: { kind: parts[0] === 'ua' ? 'ua' : 'mqtt', path: legacy.map(decodeURIComponent).join('/') } };
  }

  document.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (MENU && !e.target.closest('#cmenu')) {
      const again = e.target.closest('[data-act]') === MENU.anchor || (MENU.anchor.dataset.act === 'pmenu' && e.target.closest('[data-act="pmenu"]'));
      closeMenu();
      if (again) return;
    }
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    const c = cur();
    if (act === 'mitem') {
      const it = MENU && MENU.items[+el.dataset.i];
      closeMenu();
      if (it) copied(it.text(), it.what);
      return;
    }
    if (act === 'pmenu') { const src = shownPayload(); if (src) openMenu(el, payloadMenu(src)); return; }
    if (act === 'jkey') { e.stopPropagation(); const src = shownPayload(); if (src && src.json !== undefined) openMenu(el, keyMenu(src, el.dataset.jp)); return; }
    if (act === 'jval') { const src = shownPayload(); if (src && src.json !== undefined) copied(valText(getAt(src.json, el.dataset.jp)), 'value'); return; }
    if (act === 'cptext') { e.stopPropagation(); copied(el.dataset.text, el.dataset.what || 'value'); return; }
    if (act === 'cpval') {
      e.stopPropagation();
      const n = find(c, c.selected); const x = n && viewParts(n.view).tv.find((t) => t.key === el.dataset.key);
      if (x) copied(valText(x.val), humanize(x.key));
      return;
    }
    if (act === 'cphist') {
      const src = shownPayload(); const h = src && src.history.find((y) => y.t === +el.dataset.t);
      if (h) openMenu(el, [
        { label: src.ua ? 'Data value' : 'Payload', text: () => h.raw, what: src.ua ? 'data value' : 'payload' },
        { label: src.ua ? 'Node and value as JSON' : 'Topic and message as JSON', hint: 'with time', text: () => msgJson(src, h), what: 'message' },
      ]);
      return;
    }
    if (act === 'fmenu') {
      e.stopPropagation();
      const k = connOf(S.view); const m = k && feedItems(k.id).find((y) => y.id === +el.dataset.id);
      if (m) {
        const n = find(c, m.topic); const ua = c.key === 'ua';
        const topic = n ? (ua && n.ua ? n.ua.id : localPath(n)) : m.topic;
        openMenu(el, [
          { label: ua ? 'Data value' : 'Payload', text: () => m.text, what: ua ? 'data value' : 'payload' },
          { label: ua ? 'NodeId' : 'Topic', text: () => topic, what: ua ? 'NodeId' : 'topic' },
          { label: ua ? 'Node and value as JSON' : 'Topic and message as JSON', hint: 'with time', text: () => (n ? msgJson(n, { t: m.t, raw: m.text, retained: false }) : m.text), what: 'message' },
        ]);
      }
      return;
    }
    if (act === 'tog') {
      e.stopPropagation();
      const p = el.dataset.path;
      if (c.expanded.has(p)) { c.expanded.delete(p); c.collapsed.add(p); } else { c.expanded.add(p); c.collapsed.delete(p); }
      c.treeDirty = true; frame(true);
    } else if (act === 'sel') {
      const p = el.dataset.path;
      const n = find(c, p);
      if (n && n.children.size && el.classList.contains('row') && c.selected === p) {
        if (c.expanded.has(p)) { c.expanded.delete(p); c.collapsed.add(p); } else c.expanded.add(p);
      }
      select(p);
    } else if (act === 'open') {
      select(el.dataset.path);
    } else if (act === 'connopen') {
      if (e.target.closest('[data-act="conn"], [data-act="connedit"]')) return;
      go(`c:${el.dataset.id}`);
    } else if (act === 'treewide') {
      const L = lensOf(S.view); L.wide = !L.wide; buildPage(); frame(true);
    } else if (act === 'livetoggle') {
      const L = lensOf(S.view); L.live = !L.live; S.feedSeen = S.feedId; buildPage(); frame(true);
    } else if (act === 'nav') {
      if (e.target.closest('[data-act="close"]')) return;
      go(el.dataset.view);
    } else if (act === 'close') {
      e.stopPropagation();
      const v = el.dataset.view;
      S.tabs = S.tabs.filter((t) => t !== v);
      if (isConnView(v)) S.lens.delete(v);
      if (!S.tabs.length) S.tabs = ['conn'];
      if (S.view === v || !S.tabs.includes(S.view)) go(S.tabs[S.tabs.length - 1]); else renderTabs();
    } else if (act === 'connadd') {
      openConnDialog(null);
    } else if (act === 'connedit') {
      e.stopPropagation(); openConnDialog(el.dataset.id);
    } else if (act && act.startsWith('dlg')) {
      dialogAction(act, el, e);
    } else if (act === 'conn') {
      e.stopPropagation();
      const k = el.dataset.key;
      if (S.openConn.has(k)) S.openConn.delete(k); else S.openConn.add(k);
      renderConnections();
    } else if (act === 'agentho') {
      if (e.target.closest('a, button')) return;
      if (S.agent.handoff !== el.dataset.h) { S.agent.handoff = el.dataset.h; S.agent.dirty = true; renderAtlas(); }
    } else if (act === 'agentsrc') {
      selectAgentServer(el.dataset.id);
    } else if (act === 'agentrun') {
      startMapping();
    } else if (act === 'agentprompt') {
      if (S.agent.artifact) copyText(gagePrompt(S.agent.artifact)).then(() => { el.innerHTML = `${icon('check', 'ic-sm')}Copied`; setTimeout(() => { el.innerHTML = `${icon('copy', 'ic-sm')}Copy Gage prompt`; }, 1500); });
    } else if (act === 'agentconprompt') {
      if (S.agent.connect) copyText(connectPrompt()).then(() => { el.innerHTML = `${icon('check', 'ic-sm')}Copied`; setTimeout(() => { el.innerHTML = `${icon('copy', 'ic-sm')}Copy Gage prompt`; }, 1500); });
    } else if (act === 'agentcolprompt') {
      if (S.agent.collector) copyText(collectorPrompt()).then(() => { el.innerHTML = `${icon('check', 'ic-sm')}Copied`; setTimeout(() => { el.innerHTML = `${icon('copy', 'ic-sm')}Copy Gage prompt`; }, 1500); });
    } else if (act === 'agentcopy') {
      copyText(S.agent.brief).then(() => { el.innerHTML = `${icon('check', 'ic-sm')}Copied`; setTimeout(() => { el.innerHTML = `${icon('copy', 'ic-sm')}Copy for Gage`; }, 1500); });
    } else if (act === 'agentdl') {
      const blob = new Blob([S.agent.brief], { type: 'text/markdown' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `${S.agent.domain || 'atlas'}-gage-brief.md`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } else if (act === 'prop') {
      const n = find(c, c.selected); if (n) { n.selProp = el.dataset.key; c.viewDirty = true; frame(true); }
    } else if (act === 'tab') {
      c.tab = el.dataset.tab; c.viewDirty = true; frame(true);
    } else if (act === 'copy') {
      copyText(el.dataset.text).then(() => { el.innerHTML = icon('check', 'ic-sm'); setTimeout(() => { el.innerHTML = icon('copy', 'ic-sm'); }, 1200); });
    } else if (act === 'pause') {
      setPaused(!S.paused);
    } else if (act === 'theme') {
      const dark = !document.documentElement.classList.contains('dark');
      setTheme(dark); store.set('tb-theme', dark ? 'dark' : 'light');
    } else if (act === 'collapse') {
      const col = !$('#shell').classList.contains('collapsed');
      $('#shell').classList.toggle('collapsed', col); store.set('lookout.sidebar', col ? '0' : '1');
      $('#collapseBtn').innerHTML = icon(col ? 'chevronRight' : 'chevronLeft', 'ic-sm');
    } else if (act === 'expandAll') {
      const top = scopeTop(); if (!top) return;
      const all = (n) => { if (n.children.size) { c.expanded.add(n.path); c.collapsed.delete(n.path); n.children.forEach(all); } };
      all(top); c.treeDirty = true; frame(true);
    } else if (act === 'collapseAll') {
      const top = scopeTop(); if (!top) return;
      const all = (n) => { if (n.children.size) { c.expanded.delete(n.path); c.collapsed.add(n.path); n.children.forEach(all); } };
      top.children.forEach(all); c.expanded.add(top.path); c.treeDirty = true; frame(true);
    }
  });
  window.addEventListener('hashchange', () => {
    const h = fromHash();
    if (h.legacy) { S.pendingLegacy = h.legacy; if (S.connsLoaded) resolveLegacy(); return; }
    if (isConnView(h.view)) {
      const k = connOf(h.view);
      if (h.view !== S.view) { lensOf(h.view).local = h.path; go(h.view, false); }
      else if (k) select(h.path ? `${k.name}/${h.path}` : k.name);
    } else if (h.view !== S.view) go(h.view, false);
  });
  document.addEventListener('keydown', (e) => {
    if (MENU && e.key === 'Escape') { closeMenu(); return; }
    if (D && e.key === 'Escape') { closeDialog(); return; }
    if (D && e.target.closest && e.target.closest('#modal')) return;
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('.handoff[data-act="agentho"]')) { e.preventDefault(); S.agent.handoff = e.target.dataset.h; S.agent.dirty = true; renderAtlas(); const f = document.querySelector(`.handoff[data-h="${S.agent.handoff}"]`); if (f) f.focus(); return; }
    const typing = e.target.matches('input, textarea');
    if (e.key === 'Escape' && !typing && isConnView(S.view) && lensOf(S.view).wide) { lensOf(S.view).wide = false; buildPage(); frame(true); return; }
    if (e.key === '/' && !typing) { const f = $('#filter') || $('#connFilter'); if (f) { e.preventDefault(); f.focus(); } }
    else if (e.key === 'Escape' && typing) {
      e.target.value = '';
      if (e.target.id === 'connFilter') { S.connFilter = ''; renderConnections(); } else { cur().filter = ''; cur().treeDirty = true; lastFeed = -1; }
      e.target.blur(); frame(true);
    }
    else if (e.key === ' ' && !typing) { e.preventDefault(); setPaused(!S.paused); }
  });

  window.addEventListener('resize', closeMenu);
  document.addEventListener('wheel', (e) => { if (MENU && !MENU.el.contains(e.target)) closeMenu(); }, { passive: true });

  function setPaused(p) {
    S.paused = p;
    const b = $('#pauseBtn');
    b.classList.toggle('on', p);
    b.title = p ? 'Resume updates (Space)' : 'Pause updates (Space)';
    b.innerHTML = icon(p ? 'play' : 'pause');
    if (!p) { const c = cur(); c.treeDirty = true; c.viewDirty = true; lastFeed = -1; frame(true); }
  }
  function setTheme(dark) {
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.backgroundColor = dark ? '#121214' : '#FFFFFF';
    $('#themeBtn').innerHTML = icon(dark ? 'sun' : 'moon');
  }

  // ---------------------------------------------------------------- boot
  async function boot() {
    setTheme(document.documentElement.classList.contains('dark'));
    setPaused(false);
    const collapsed = store.get('lookout.sidebar') === '0';
    $('#shell').classList.toggle('collapsed', collapsed);
    $('#collapseBtn').innerHTML = icon(collapsed ? 'chevronRight' : 'chevronLeft', 'ic-sm');

    let cfg = {};
    try { cfg = await (await fetch('config.json', { cache: 'no-store' })).json(); } catch { cfg = {}; }
    const qs = new URLSearchParams(location.search);
    uaUrl = qs.get('gateway') || cfg.opcuaGateway || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/stream/ws`;
    apiBase = typeof cfg.apiBase === 'string' ? cfg.apiBase : (cfg.opcuaGateway ? cfg.opcuaGateway.replace(/^ws/, 'http').replace(/\/api\/(opcua|stream)\/ws$/, '') : '');
    if (cfg.title) { $('#appSub').textContent = cfg.title; document.title = `Timebase ${cfg.title}`; }

    const h = fromHash();
    if (h.legacy) S.pendingLegacy = h.legacy;
    if (isConnView(h.view)) lensOf(h.view).local = h.path;
    if (h.view !== 'conn') S.tabs.push(h.view);
    go(h.view, false);
    connectUa();
  }
  boot();
})();
