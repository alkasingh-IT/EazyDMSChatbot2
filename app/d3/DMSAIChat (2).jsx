import { useState, useEffect, useRef, useCallback, useMemo } from "react";

/* ═══════════════════════════════════════════════════════════════════
   SESSION HELPERS (localStorage, matches DMS app.js)
   ═══════════════════════════════════════════════════════════════════ */
const SESS_PREFIX = 'dmsSessions_';
const getSessKey = (uid) => SESS_PREFIX + (uid || 'anon');

const getLocalDateKey = (date = new Date()) => {
  const d = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const getSessionDateKey = (session) => session?.dateKey || getLocalDateKey(session?.created || session?.updated);

const loadSessions = (uid) => {
  try {
    return JSON.parse(localStorage.getItem(getSessKey(uid)) || '[]');
  } catch {
    return [];
  }
};

const saveSessions = (uid, list) => {
  try {
    localStorage.setItem(getSessKey(uid), JSON.stringify(list.slice(0, 40)));
  } catch {}
};

const createNewSession = (uid) => {
  const id = String(Date.now());
  const list = loadSessions(uid);
  list.unshift({
    id,
    title: 'New Chat',
    created: new Date().toISOString(),
    updated: new Date().toISOString(),
    dateKey: getLocalDateKey(),
    messages: []
  });
  saveSessions(uid, list);
  return id;
};

const autoSaveSession = (uid, sid, messages, snapshot = null) => {
  const list = loadSessions(uid);
  let idx = list.findIndex(x => x.id === sid);
  if (idx < 0) {
    list.unshift({
      id: sid,
      title: 'New Chat',
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      dateKey: getLocalDateKey(),
      messages: []
    });
    idx = 0;
  }
  // Attach the data snapshot (cols/rows/chart/briefing) to the LAST assistant
  // message so multi-turn replay can rebuild the report card (SFA parity).
  const enriched = (snapshot && snapshot.rows?.length) ? [...messages] : [...messages];
  if (snapshot && snapshot.rows?.length) {
    for (let i = enriched.length - 1; i >= 0; i--) {
      if (enriched[i].role === 'assistant') { enriched[i] = { ...enriched[i], data_snapshot: snapshot }; break; }
    }
  }
  list[idx].messages = [...enriched];
  list[idx].updated = new Date().toISOString();
  list[idx].dateKey = list[idx].dateKey || getSessionDateKey(list[idx]);
  if (snapshot) list[idx].data_snapshot = snapshot;
  if (list[idx].title === 'New Chat') {
    const first = messages.find(m => m.role === 'user');
    if (first) {
      list[idx].title = first.content.slice(0, 50) + (first.content.length > 50 ? '...' : '');
    }
  }
  saveSessions(uid, list);
};

const deleteSession = (uid, sid) => {
  const list = loadSessions(uid).filter(x => x.id !== sid);
  saveSessions(uid, list);
  return list;
};

const renameSession = (uid, sid, title) => {
  const list = loadSessions(uid);
  const idx = list.findIndex(x => x.id === sid);
  if (idx >= 0) {
    list[idx].title = title || 'Untitled';
    saveSessions(uid, list);
  }
  return list;
};

const formatTimeAgo = (isoString) => {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return new Date(isoString).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
};

/* ═══════════════════════════════════════════════════════════════════
   UTILITY HELPERS (numbers, labels, markdown)
   ═══════════════════════════════════════════════════════════════════ */
function isNumber(v) {
  if (v === null || v === undefined || typeof v === "boolean") return false;
  if (typeof v === "number" && !Number.isNaN(v)) return true;
  return Number.isFinite(Number(v));
}

function isBlankOrNull(v) {
  if (v === null || v === undefined) return true;
  if (typeof v === "string") {
    const t = v.trim().toLowerCase();
    return t === "" || t === "null" || t === "none";
  }
  return false;
}

function displayCellValue(v) {
  return isBlankOrNull(v) ? "" : v.toString();
}

const COLUMN_LABEL_MAP = {
  order_type: "Order Type",
  order_type_name: "Order Type",
  total_item_selling_price: "Total Sales Amount",
  total_selling_price: "Total Sales Amount",
  selling_price: "Selling Price",
  total_item_quantity: "Total Quantity",
  total_quantity: "Total Quantity",
  quantity: "Quantity",
  qty: "Quantity",
  created_at: "Created Date",
  create_date: "Created Date",
  updated_at: "Updated Date",
  staff_name: "Staff Member",
  staff_id: "Staff Member",
  staff_uid: "Staff Member",
  outlet_name: "Outlet Name",
  outlet_id: "Outlet",
  customer_name: "Customer Name",
  customer_id: "Customer",
  product_name: "Product Name",
  item_name: "Item Name",
  category_name: "Product Category",
  van_name: "Van / Vehicle",
  van_id: "Van / Vehicle",
  route_name: "Route / Territory",
  route_id: "Route / Territory",
  order_count: "Total Orders",
  total_orders: "Total Orders",
  bill_amount: "Total Bill Amount",
  total_amount: "Total Amount",
  grand_total: "Grand Total",
  net_amount: "Net Amount",
  net_val: "Net Value",
  distributor_name: "Distributor Name",
  salesman_name: "Salesman Name"
};

function formatColumnLabel(col) {
  if (!col || typeof col !== "string") return col || "";
  const cleanCol = col.trim();
  const lowerCol = cleanCol.toLowerCase();
  if (COLUMN_LABEL_MAP[lowerCol]) return COLUMN_LABEL_MAP[lowerCol];
  let s = cleanCol.replace(/^(tbl_|tb_|ref_|dim_|fact_)/i, "");
  s = s.replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
  return s
    .split(" ")
    .map(w => {
      const lw = w.toLowerCase();
      if (lw === "id") return "ID";
      if (lw === "sku") return "SKU";
      if (lw === "sfa") return "SFA";
      if (lw === "qty") return "Qty";
      if (lw === "amt") return "Amount";
      if (lw === "val") return "Value";
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    })
    .join(" ");
}

function suggestAxes(cols, rows) {
  // Smarter defaults: date/named dimensions on X, measure-like numerics on Y.
  // Falls back gracefully so the dropdowns always start somewhere sensible.
  const sample = (rows || []).slice(0, 60);
  const idPat = /(^|_)(id|ids|code|no|number|sl|sr|serial|uuid|key|index|year|yr)$/i;
  const measurePat = /(value|sales|amount|revenue|qty|quantity|units|orders|order|count|total|net|gross|price|discount|margin|stock|collection|outstanding|volume|weight|cases|pieces|pcs|inr|rs|sum|avg|score|compliance|visit|hours|target|achievement)/i;
  const dimPat = /(name|outlet|sku|product|distributor|dealer|zone|region|state|city|territory|category|brand|channel|month|week|day|date|period|employee|staff|team|beat|route|type|status|group|segment|depot|plant|vendor|customer|item|material|reason|mode)/i;
  const cell = (r, c) => (r ? r[c] : null);
  const nonBlank = (c) => sample.map(r => cell(r, c)).filter(v => v !== null && v !== undefined && String(v).trim() !== "");
  const dateRatio = (c) => {
    const vs = nonBlank(c);
    if (!vs.length) return 0;
    const hits = vs.filter(v => /^\d{4}[-/]\d{1,2}/.test(String(v)) || /^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}/.test(String(v))).length;
    return hits / vs.length;
  };
  const numeric = [], dims = [];
  for (const c of cols) {
    const vs = nonBlank(c);
    const numRatio = vs.length ? vs.filter(isNumber).length / vs.length : 0;
    if (vs.length && numRatio >= 0.6 && dateRatio(c) < 0.6 && !idPat.test(c)) numeric.push(c);
    else dims.push(c);
  }
  const distinctCount = (c) => new Set(sample.map(r => String(cell(r, c)))).size;
  // X: real date column > named dimension > low-cardinality column > non id-like > first
  const x = dims.find(c => dateRatio(c) >= 0.6)
       || dims.find(c => dimPat.test(c) && !idPat.test(c))
       || dims.find(c => !idPat.test(c) && distinctCount(c) <= Math.max(15, Math.ceil(sample.length / 2)))
       || dims.find(c => !idPat.test(c))
       || dims[0] || cols[0] || "";
  // Y: named measure > largest numeric magnitude > first numeric
  const yScore = (c) => {
    const nums = nonBlank(c).filter(isNumber).map(Number);
    const total = nums.reduce((s, v) => s + Math.abs(v), 0);
    return (measurePat.test(c) ? 1e15 : 0) + total;
  };
  let y = numeric.slice().sort((a, b) => yScore(b) - yScore(a))[0] || "";
  if (!y) y = cols.find(c => c !== x) || x;
  return { x, y };
}

function escHtml(s = "") {
  return s.toString().replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

// ─── Exact-UI PDF capture (renders the on-screen report to a PDF image) ──────
function _loadScriptOnce(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (existing.dataset.loaded === "1") { resolve(); return; }
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("load failed")));
      return;
    }
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.onload = () => { s.dataset.loaded = "1"; resolve(); };
    s.onerror = () => reject(new Error("load failed: " + src));
    document.head.appendChild(s);
  });
}

async function _ensurePdfLibs() {
  if (!window.html2canvas) await _loadScriptOnce("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
  if (!window.jspdf) await _loadScriptOnce("https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js");
}

async function _captureNodesToPdf(nodes, filename) {
  if (!nodes || !nodes.length) return false;
  await _ensurePdfLibs();
  if (!window.html2canvas || !window.jspdf) return false;
  const { jsPDF } = window.jspdf;
  const pdf = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const margin = 24;
  const contentW = pageW - margin * 2;
  const pageContentH = pageH - margin * 2;
  let first = true;
  for (const el of nodes) {
    const canvas = await window.html2canvas(el, { backgroundColor: "#ffffff", scale: 2, useCORS: true, logging: false });
    const img = canvas.toDataURL("image/png");
    const imgH = canvas.height * (contentW / canvas.width);
    if (!first) pdf.addPage();
    first = false;
    let heightLeft = imgH;
    let position = margin;
    pdf.addImage(img, "PNG", margin, position, contentW, imgH);
    heightLeft -= pageContentH;
    while (heightLeft > 0) {
      position = margin - (imgH - heightLeft);
      pdf.addPage();
      pdf.addImage(img, "PNG", margin, position, contentW, imgH);
      heightLeft -= pageContentH;
    }
  }
  pdf.save(filename);
  return true;
}

async function captureReportCardPdf(el) {
  try {
    if (!el) { alert("Nothing to export."); return false; }
    const ok = await _captureNodesToPdf([el], `Owzy_Report_${Date.now()}.pdf`);
    if (!ok) alert("PDF export is unavailable right now.");
    return ok;
  } catch (e) {
    console.warn("[pdf] exact-UI capture failed:", e);
    alert("PDF export failed. Please try again.");
    return false;
  }
}

// ─── Voice capture helpers (raw PCM → 16kHz WAV for /api/speech/transcribe) ──
function resampleAudio(srcSamples, srcRate, tgtRate) {
  if (srcRate === tgtRate) return srcSamples;
  const ratio = tgtRate / srcRate;
  const len = Math.floor(srcSamples.length * ratio);
  const resampled = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    const srcIdx = i / ratio;
    const srcIdxFloor = Math.floor(srcIdx);
    const srcIdxCeil = Math.min(srcIdxFloor + 1, srcSamples.length - 1);
    const frac = srcIdx - srcIdxFloor;
    resampled[i] = srcSamples[srcIdxFloor] + (srcSamples[srcIdxCeil] - srcSamples[srcIdxFloor]) * frac;
  }
  return resampled;
}

function floatTo16BitPCM(input) {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}
function encodeWav(pcm16, sampleRate) {
  const buffer = new ArrayBuffer(44 + pcm16.length * 2);
  const view = new DataView(buffer);
  const ws = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); view.setUint32(4, 36 + pcm16.length * 2, true); ws(8, "WAVE");
  ws(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); ws(36, "data");
  view.setUint32(40, pcm16.length * 2, true);
  let offset = 44;
  for (let i = 0; i < pcm16.length; i++, offset += 2) view.setInt16(offset, pcm16[i], true);
  return buffer;
}

function friendlyErrorMessage(error, fallback = 'Something went wrong. Please try again.') {
  const message = String(error?.message || error || '').toLowerCase();
  if (message.includes('401') || message.includes('authenticated') || message.includes('u-uid')) {
    return 'Your session could not be verified. Please refresh the page and try again.';
  }
  if (message.includes('403') || message.includes('not belong')) {
    return 'You do not have permission to access this conversation.';
  }
  if (message.includes('429') || message.includes('too many')) {
    return 'The service is busy right now. Please wait a moment and try again.';
  }
  // Check gateway/timeout codes BEFORE the generic 'server error' branch,
  // otherwise a 504 proxy timeout is reported as a generic 500.
  if (message.includes('502') || message.includes('503') || message.includes('504') || message.includes('gateway')) {
    return 'The request took too long and was stopped by the gateway. Try a narrower date range, or ask again.';
  }
  if (message.includes('timeout') || message.includes('timed out')) {
    return 'The request took too long. Please try again.';
  }
  if (message.includes('network') || message.includes('failed to fetch') || message.includes('connection')) {
    return 'We could not connect to the service. Please check your connection and try again.';
  }
  if (message.includes('could not be stored')) {
    return 'Your response could not be saved safely. Please try again.';
  }
  if (message.includes('500') || message.includes('server error')) {
    return 'The service is temporarily unavailable. Please try again shortly.';
  }
  return fallback;
}

/* ═══════════════════════════════════════════════════════════════════
   MARKDOWN RENDERER — nac-styled output
   ═══════════════════════════════════════════════════════════════════ */
function renderMarkdown(text, isStreaming = false) {
  if (!text) return '<div class="nac-md-content"><em>No response.</em></div>';
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="nac-md-code">$1</code>');
  const srcLines = String(text).split('\n');

  // Pass 1: extract markdown tables into standalone HTML nodes.
  const nodes = [];
  let i = 0;
  while (i < srcLines.length) {
    if (/^\s*\|/.test(srcLines[i])) {
      const t = [];
      while (i < srcLines.length && /^\s*\|/.test(srcLines[i])) t.push(srcLines[i++]);
      if (t.length >= 2) {
        const hdrs = t[0].split("|").slice(1, -1).map(c => c.trim());
        const body = /^[\s|:\-]+$/.test(t[1]) ? t.slice(2) : t.slice(1);
        let html = '<div class="nac-md-tbl-wrap"><table class="nac-md-table"><thead><tr>';
        hdrs.forEach(h => { html += "<th>" + inline(escHtml(h)) + "</th>"; });
        html += "</tr></thead><tbody>";
        body.forEach(row => {
          const cells = row.split("|").slice(1, -1);
          html += "<tr>" + cells.map(c => "<td>" + inline(escHtml(c.trim())) + "</td>").join("") + "</tr>";
        });
        html += "</tbody></table></div>";
        nodes.push({ type: "html", html });
      } else {
        t.forEach(l => nodes.push({ type: "p", text: l }));
      }
    } else {
      nodes.push({ type: "raw", text: srcLines[i++] });
    }
  }

  // Pass 2: group raw lines into headings / lists / paragraphs (no stray <br>).
  const blocks = [];
  let list = null;
  const flush = () => { if (list) { blocks.push(list); list = null; } };
  for (const n of nodes) {
    if (n.type !== "raw") { flush(); blocks.push(n); continue; }
    const trimmed = n.text.trim();
    if (!trimmed) { flush(); continue; }
    let m;
    if ((m = trimmed.match(/^#{1,2}\s+(.+)$/))) { flush(); blocks.push({ type: "h1", text: m[1] }); continue; }
    if ((m = trimmed.match(/^###\s+(.+)$/))) { flush(); blocks.push({ type: "h2", text: m[1] }); continue; }
    if ((m = trimmed.match(/^####\s+(.+)$/))) { flush(); blocks.push({ type: "h3", text: m[1] }); continue; }
    if ((m = trimmed.match(/^[-*\u2022]\s+(.+)$/))) {
      if (!list || list.ordered) { flush(); list = { type: "ul", items: [] }; }
      list.items.push(m[1]); continue;
    }
    if ((m = trimmed.match(/^\d+\.\s+(.+)$/))) {
      if (!list || !list.ordered) { flush(); list = { type: "ol", ordered: true, items: [] }; }
      list.items.push(m[1]); continue;
    }
    if (/^-{3,}$/.test(trimmed)) { flush(); blocks.push({ type: "hr" }); continue; }
    flush(); blocks.push({ type: "p", text: trimmed });
  }
  flush();

  // Pass 3: render to HTML.
  let html = "";
  for (const b of blocks) {
    if (b.type === "html") html += b.html;
    else if (b.type === "h1") html += `<div class="nac-md-h1">${inline(escHtml(b.text))}</div>`;
    else if (b.type === "h2") html += `<div class="nac-md-h2">${inline(escHtml(b.text))}</div>`;
    else if (b.type === "h3") html += `<div class="nac-md-h3">${inline(escHtml(b.text))}</div>`;
    else if (b.type === "hr") html += `<hr class="nac-md-hr"/>`;
    else if (b.type === "ul") html += `<ul class="nac-md-bullets">${b.items.map(it => `<li>${inline(escHtml(it))}</li>`).join("")}</ul>`;
    else if (b.type === "ol") html += `<ol class="nac-md-numbered">${b.items.map(it => `<li>${inline(escHtml(it))}</li>`).join("")}</ol>`;
    else if (b.type === "p") html += `<p>${inline(escHtml(b.text))}</p>`;
  }
  if (isStreaming) html += '<span class="nac-snapshot-streaming-cursor"></span>';
  return '<div class="nac-md-content">' + html + '</div>';
}

function MarkdownContent({ text }) {
  return (
    <div>
      <div className="nac-md-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   CHART UTILITIES (ported from Native AI Chat)
   ═══════════════════════════════════════════════════════════════════ */
const VIBRANT_PALETTE = [
  '#4f46e5','#6366f1','#6d5cf6','#a5b4fc','#6366f1',
  '#6d5cf6','#4338ca','#6d5cf6','#4338ca','#818cf8',
  '#7c3aed','#6d5cf6','#4338ca','#818cf8','#3730a3','#a5b4fc'
];

function getMultiColors(count, opacity = 0.85) {
  const bgColors = [], borderColors = [];
  for (let i = 0; i < count; i++) {
    const hex = VIBRANT_PALETTE[i % VIBRANT_PALETTE.length];
    borderColors.push(hex);
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    bgColors.push(`rgba(${r},${g},${b},${opacity})`);
  }
  return { bgColors, borderColors };
}

function nacFmtTick(val) {
  const n = parseFloat(val);
  if (isNaN(n)) return val;
  if (Math.abs(n) >= 1e7) return '₹' + (n/1e7).toFixed(1) + 'Cr';
  if (Math.abs(n) >= 1e5) return '₹' + (n/1e5).toFixed(1) + 'L';
  if (Math.abs(n) >= 1e3) return '₹' + (n/1e3).toFixed(0) + 'k';
  return String(n);
}

// Shared chart data prep:
//  - date-ish x: chronological, capped at 12 points
//  - otherwise: top 8 by value + aggregated "Others" bucket so labels stay readable
function chartSeries(rows, xCol, yCol) {
  const clean = (rows || []).filter(r => r && r[xCol] != null && String(r[xCol]).trim() !== "");
  const isDate = clean.length > 0 && /^\d{4}[-/]\d{2}/.test(String(clean[0][xCol]));
  let series;
  if (isDate) {
    series = sortChartRows(clean.slice(0, 12), xCol).map(r => {
      const v = isNumber(r[yCol]) ? Number(r[yCol]) : 0;
      return [String(r[xCol]).substring(0, 12), v];
    });
  } else {
    const ranked = clean
      .map(r => [String(r[xCol] == null ? "" : r[xCol]).substring(0, 26), isNumber(r[yCol]) ? Number(r[yCol]) : 0])
      .sort((a, b) => b[1] - a[1]);
    const TOP = 8;
    if (ranked.length <= TOP) {
      series = ranked;
    } else {
      const top = ranked.slice(0, TOP);
      const rest = ranked.slice(TOP);
      const othersVal = rest.reduce((s, r) => s + r[1], 0);
      top.push([`Others (${rest.length})`, othersVal]);
      series = top;
    }
  }
  return { labels: series.map(s => s[0]), values: series.map(s => (Number.isFinite(s[1]) ? s[1] : null)) };
}

// Consistent, readable chart height. Horizontal bars grow with category count.
function chartHeightFor(labels, chartType, expanded = false) {
  const n = (labels || []).length;
  const isPie = chartType === "pie" || chartType === "doughnut";
  const isLine = chartType === "line";
  const avgLen = n ? labels.reduce((s, l) => s + String(l).length, 0) / n : 0;
  const horizontal = !isPie && !isLine && (n > 6 || avgLen > 12);
  if (expanded) return horizontal ? Math.max(420, Math.min(n, 16) * 34) : 420;
  if (isPie) return 250;
  if (isLine) return 230;
  return horizontal ? Math.max(240, Math.min(n, 10) * 30) : 240;
}

function buildChartInstance(canvas, type, labels, values, yLabel, showDataLabels = false, size = {}) {
  const responsive = size.responsive !== false;
  const fixedH = size.height || 0;
  if (fixedH) canvas.style.height = fixedH + "px";
  const count = labels.length;
  const palette = getMultiColors(count, 0.85);
  // Chart.js 4 removed the 'horizontalBar' controller → bar + indexAxis:'y'.
  let isHorizontal = type === 'horizontalBar' || type === 'horizontalbar';
  if (isHorizontal) type = 'bar';
  const isPie = type === 'pie' || type === 'doughnut';
  const isLine = type === 'line';
  const isSparse = count <= 3;
  // Auto-orient bars horizontally when many categories / long names so labels
  // get a full row and values stay readable (no rotated tick soup).
  const _avgLen = count ? labels.reduce((s, l) => s + String(l).length, 0) / count : 0;
  if (!isPie && !isLine && type === 'bar' && (count > 6 || _avgLen > 12)) isHorizontal = true;
  const truncTick = (v) => {
    const s = String(v == null ? '' : v);
    return s.length > 16 ? s.slice(0, 15) + '…' : s;
  };

  const customDatalabelsPlugin = {
    id: 'nacDataLabels',
    afterDatasetsDraw: (chart) => {
      if (!showDataLabels) return;
      const ctx = chart.ctx;
      ctx.save();
      ctx.font = "600 9.5px 'Inter', sans-serif";
      const isPieChart = chart.config.type === 'doughnut' || chart.config.type === 'pie';
      const isHoriz = chart.config.options?.indexAxis === 'y';

      chart.data.datasets.forEach((dataset, datasetIndex) => {
        const meta = chart.getDatasetMeta(datasetIndex);
        if (!meta || meta.hidden) return;

        if (isPieChart) {
          const total = dataset.data.reduce((s, v) => s + (Number(v) || 0), 0);
          meta.data.forEach((element, index) => {
            const val = dataset.data[index];
            if (val === null || val === undefined || isNaN(val) || val === 0) return;
            const pct = total > 0 ? (val / total) * 100 : 0;
            if (pct < 6) return; // don't crowd tiny slices
            if (element && typeof element.tooltipPosition === 'function') {
              const pos = element.tooltipPosition();
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.fillStyle = '#ffffff';
              ctx.shadowColor = 'rgba(0,0,0,0.55)';
              ctx.shadowBlur = 3;
              ctx.fillText(nacFmtTick(val), pos.x, pos.y);
              ctx.shadowBlur = 0;
            }
          });
          return;
        }

        const n = meta.data.length;
        if (n > 8) return; // too many points: leave values to the tooltip
        let lastX = -999;
        meta.data.forEach((element, index) => {
          const val = dataset.data[index];
          if (val === null || val === undefined || isNaN(val) || val === 0) return;
          if (!element || typeof element.tooltipPosition !== 'function') return;
          const text = nacFmtTick(val);
          const pos = element.tooltipPosition();
          const textWidth = ctx.measureText(text).width;

          if (isHoriz) {
            const fitsRight = pos.x + textWidth + 14 < chart.chartArea.right;
            ctx.textAlign = fitsRight ? 'left' : 'right';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = fitsRight ? '#334155' : '#ffffff';
            ctx.fillText(text, fitsRight ? pos.x + 6 : pos.x - 6, pos.y);
          } else if (isLine) {
            if (Math.abs(pos.x - lastX) < 26) return;
            lastX = pos.x;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillStyle = '#4338ca';
            ctx.fillText(text, pos.x, pos.y - 6);
          } else {
            if (pos.x - textWidth / 2 < lastX + 4) return;
            lastX = pos.x + textWidth / 2;
            const nearTop = pos.y < 18;
            ctx.textAlign = 'center';
            ctx.textBaseline = nearTop ? 'top' : 'bottom';
            ctx.fillStyle = nearTop ? '#4338ca' : '#334155';
            ctx.fillText(text, pos.x, nearTop ? pos.y + 4 : pos.y - 4);
          }
        });
      });
      ctx.restore();
    }
  };

  if (isPie) {
    return new window.Chart(canvas, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: palette.bgColors, borderColor: '#ffffff', borderWidth: 2, hoverOffset: 6 }] },
      plugins: [customDatalabelsPlugin],
      options: {
        responsive, maintainAspectRatio: false, cutout: '65%',
        animation: { duration: 750, easing: 'easeOutQuart' },
        plugins: {
          legend: { position: 'right', labels: { color: '#475569', font: { size: 11, weight: '600' }, usePointStyle: true, padding: 12 } },
          tooltip: { backgroundColor: 'rgba(15,23,42,0.92)', borderColor: 'rgba(79, 70, 229,0.28)', borderWidth: 1, padding: 12, cornerRadius: 10, titleColor: '#fff', bodyColor: '#e2e8f0' },
          datalabels: { display: false },
        },
      },
    });
  }

  const maxVal = Math.max(...values.filter(v => v != null && !isNaN(v)), 0);
  const minBarLen = maxVal > 0 ? Math.min(8, Math.max(4, Math.round(maxVal * 0.015))) : 4;
  let bg, border, pointBg;

  if (isLine) {
    const ctx2d = canvas.getContext('2d');
    const gradient = ctx2d.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, 'rgba(79, 70, 229,0.30)');
    gradient.addColorStop(0.6, 'rgba(99, 102, 241,0.12)');
    gradient.addColorStop(1, 'rgba(165, 180, 252,0.02)');
    bg = gradient; border = '#4f46e5';
    pointBg = labels.map((_, i) => VIBRANT_PALETTE[i % VIBRANT_PALETTE.length]);
  } else {
    bg = palette.bgColors; border = palette.borderColors;
  }

  return new window.Chart(canvas, {
    type,
    data: { labels, datasets: [{
      label: yLabel, data: values,
      backgroundColor: bg, borderColor: border,
      borderWidth: isLine ? 3 : 1.5,
      borderRadius: type === 'bar' ? 8 : 0,
      borderSkipped: false,
      minBarLength: isLine ? undefined : minBarLen,
      fill: isLine, tension: isSparse ? 0.0 : 0.38, spanGaps: true,
      pointBackgroundColor: isLine ? pointBg : border,
      pointBorderColor: '#fff',
      pointBorderWidth: isLine ? (isSparse ? 3 : 2) : 1,
      pointRadius: isLine ? (isSparse ? 9 : 4.5) : 0,
      pointHoverRadius: isLine ? (isSparse ? 13 : 7) : 0,
    }]},
    plugins: [customDatalabelsPlugin],
    options: {
      responsive, maintainAspectRatio: false,
      indexAxis: isHorizontal ? 'y' : 'x',
      animation: { duration: 750, easing: 'easeOutQuart' },
      layout: {
        padding: isHorizontal
          ? { top: 10, right: 34, bottom: 2, left: 2 }
          : { top: 22, right: 8, bottom: 2, left: 2 },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15,23,42,0.92)', borderColor: 'rgba(79, 70, 229,0.28)', borderWidth: 1,
          padding: 12, cornerRadius: 10, titleColor: '#fff', bodyColor: '#e2e8f0',
          callbacks: { label: (ctx) => { const v = isHorizontal ? (ctx.parsed.x ?? ctx.parsed) : (ctx.parsed.y ?? ctx.parsed); return (ctx.dataset.label||'') + ': ' + nacFmtTick(v); } }
        },
        datalabels: { display: false },
      },
      scales: isHorizontal ? {
        x: { beginAtZero: true, ticks: { color: '#8a94a6', font: { size: 10, weight: '500' }, callback: nacFmtTick, maxTicksLimit: 6 }, grid: { color: 'rgba(79, 70, 229,.07)' } },
        y: { ticks: { color: '#334155', font: { size: 10.5, weight: '600' }, autoSkip: false, callback: (v) => truncTick(labels[v]) }, grid: { display: false } },
      } : (isLine ? {
        x: { ticks: { color: '#8a94a6', font: { size: 9.5, weight: '500' }, maxRotation: 0, minRotation: 0, autoSkip: true, maxTicksLimit: 8 }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: '#8a94a6', font: { size: 10.5, weight: '500' }, callback: nacFmtTick, maxTicksLimit: 6 }, grid: { color: 'rgba(79, 70, 229,.07)' } },
      } : {
        x: { ticks: { color: '#334155', font: { size: 10, weight: '600' }, maxRotation: 0, minRotation: 0, autoSkip: false, callback: (v) => truncTick(labels[v]) }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: '#8a94a6', font: { size: 10.5, weight: '500' }, callback: nacFmtTick, maxTicksLimit: 6 }, grid: { color: 'rgba(79, 70, 229,.07)' } },
      }),
    },
  });
}

function sortChartRows(rows, xCol) {
  return rows.slice().sort((a, b) => {
    const av = a[xCol], bv = b[xCol];
    if (av == null) return -1; if (bv == null) return 1;
    const aStr = String(av), bStr = String(bv);
    if (/^\d{4}[-/]\d{2}/.test(aStr) && /^\d{4}[-/]\d{2}/.test(bStr)) return aStr < bStr ? -1 : aStr > bStr ? 1 : 0;
    const aNum = parseFloat(av), bNum = parseFloat(bv);
    if (!isNaN(aNum) && !isNaN(bNum)) return aNum - bNum;
    return aStr < bStr ? -1 : aStr > bStr ? 1 : 0;
  });
}

/* ═══════════════════════════════════════════════════════════════════
   SUB-COMPONENTS — CodeBlock, ChatBubble, ThinkingState, ResultTable, NacModal
   ═══════════════════════════════════════════════════════════════════ */
function CodeBlock({ label, code }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div className="nac-code-label">{label}</div>
      <pre className="nac-code-pre">{code}</pre>
    </div>
  );
}

function ChatBubble({ role, title, body, children, onSpeak, isSpeaking, speechSupported, turnId }) {
  const isUser = role === "user";
  const showSpeakBtn = !isUser && speechSupported && !!onSpeak;
  return (
    <div className={`nac-bubble ${isUser ? "nac-bubble--user" : "nac-bubble--assistant"}`} data-turn-body={turnId}>
      {!isUser && (
        <div className="nac-msg-avatar nac-msg-avatar--assistant" title="Owzy">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z"/>
          </svg>
        </div>
      )}
      <div className={`nac-bubble-content ${isUser ? "nac-bubble-content--user" : "nac-bubble-content--assistant"}`}>
        <div className={`nac-bubble-title ${isUser ? "nac-bubble-title--user" : "nac-bubble-title--assistant"}`}>{title}</div>
        <div className="nac-bubble-body">
          {typeof body === "string" && !isUser ? <MarkdownContent text={body} /> : body}
        </div>
        {children && <div className="nac-bubble-extra">{children}</div>}
        {showSpeakBtn && (
          <button
            type="button"
            className={`nac-btn-speak${isSpeaking ? " nac-btn-speak--active" : ""}`}
            onClick={onSpeak}
            title={isSpeaking ? "Stop speaking" : "Read this message aloud"}
          >
            {isSpeaking ? "■" : "🔊"}
          </button>
        )}
      </div>
      {isUser && (
        <div className="nac-msg-avatar nac-msg-avatar--user" title="You">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </div>
      )}
    </div>
  );
}

function ThinkingState() {
  return (
    <div className="nac-thinking-container">
      <div className="nac-thinking-bar-wrap">
        <div className="nac-thinking-bar-fill" />
      </div>
    </div>
  );
}

// ─── Owzy branded report card (parity with SFA) ──────────────────────────────

function NabIcon({ type }) {
  const s = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (type) {
    case "units": return <svg {...s}><path d="M4 20V10M12 20V4M20 20v-7"/></svg>;
    case "orders": return <svg {...s}><rect x="5" y="3" width="14" height="18" rx="2"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="13" y2="16"/></svg>;
    case "skus": return <svg {...s}><path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/></svg>;
    case "outlets": return <svg {...s}><path d="M4 10l2-6h12l2 6"/><path d="M4 8v11a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8"/><path d="M9 20v-6h6v6"/></svg>;
    case "value": return <svg {...s}><path d="M5 20V10M12 20V4M19 20v-9"/></svg>;
    case "pulse": return <svg {...s}><path d="M3 12h4l2-6 4 12 2-6h5"/></svg>;
    case "trend": return <svg {...s}><polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/></svg>;
    case "shield": return <svg {...s}><path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z"/></svg>;
    case "link": return <svg {...s}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L11 16"/></svg>;
    case "spread": return <svg {...s}><path d="M12 3v18M5 8l14 8M19 8L5 16"/></svg>;
    case "search": return <svg {...s}><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></svg>;
    default: return <svg {...s}><circle cx="12" cy="12" r="9"/></svg>;
  }
}

const NAB_TIER_COLORS = { ANCHOR: "#4f46e5", CORE: "#6366f1", TAIL: "#a5b4fc", DORMANT: "#e3e9f2" };

function OwzyBriefingCard({ b, aiHtml, aiGenerating, onExplore }) {
  const donutRef = useRef(null);
  const cardRef = useRef(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  useEffect(() => {
    if (!donutRef.current || !window.Chart || !(b.tiers || []).length) return;
    const c = new window.Chart(donutRef.current, {
      type: "doughnut",
      data: {
        labels: (b.tiers || []).map(t => t.tier),
        datasets: [{
          data: (b.tiers || []).map(t => t.count),
          backgroundColor: (b.tiers || []).map(t => NAB_TIER_COLORS[t.tier] || "#4f46e5"),
          borderColor: "#fff", borderWidth: 2, hoverOffset: 4,
        }],
      },
      options: { responsive: true, maintainAspectRatio: false, cutout: "70%", plugins: { legend: { display: false }, tooltip: { enabled: false } } },
    });
    return () => { try { c.destroy(); } catch (_) {} };
  }, [b]);

  if (!b || !b.tiles) return null;
  const totalSkus = (b.tiers || []).reduce((s, t) => s + t.count, 0);

  return (
    <div className="nab-card" ref={cardRef}>
      <div className="nab-top">
        <span className="nab-brand">Owzy</span>
        {(b.date_from || b.date_to) ? (
          <span className="nab-range-pill">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
            {b.date_from} <span className="nab-range-arrow">→</span> {b.date_to || "Today"}
          </span>
        ) : null}
      </div>
      <h1 className="nab-title">{b.title}</h1>
      <div className="nab-subrow">
        <p className="nab-intro">{b.intro}{b.date_from ? <span> for <strong>{b.date_from} to {b.date_to || "today"}</strong>.</span> : "."}</p>
      </div>
      <div className="nab-row2">
        <div className="nab-tiles">
          {(b.tiles || []).map((t, i) => (
            <div className="nab-tile" key={i}>
              <span className="nab-tile-ic"><NabIcon type={t.icon} /></span>
              <div>
                <div className="nab-tile-val">{t.value}</div>
                <div className="nab-tile-lbl">{t.label}</div>
              </div>
            </div>
          ))}
        </div>
        {b.value ? (
          <div className="nab-value-card">
            <span className="nab-value-icon"><NabIcon type="value" /></span>
            <div>
              <div className="nab-value-num">{b.value}</div>
              <div className="nab-value-lbl">{b.value_label}</div>
            </div>
          </div>
        ) : null}
      </div>
      <div className="nab-meta-row">
        {b.biggest && b.biggest.name ? (
          <span className="nab-biggest">{b.biggest.label}: <strong>{b.biggest.name}</strong> ({b.biggest.share}% of the {(b.value_label || "").toLowerCase()}).</span>
        ) : null}
        {(b.avg_bits || []).length ? <span className="nab-avg">{b.avg_bits.join("  |  ")}</span> : null}
      </div>

      {((b.leaders || []).length || (b.tiers || []).length) ? (
      <div className="nab-grid2">
        {(b.leaders || []).length ? (
        <div className="nab-panel nab-panel--leaders">
          <div className="nab-panel-title">Top Items</div>
          <div className="nab-leaders-scroll">
            <table className="nab-table">
              <thead><tr><th>#</th><th>Name</th><th>Value</th><th>Share</th><th>Units</th></tr></thead>
              <tbody>
                {(b.leaders || []).map((l, i) => l.rest ? (
                  <tr className="nab-tr-rest" key={"rest"}>
                    <td className="nab-td-rest">...</td>
                    <td className="nab-td-restname"><strong>{l.name || "Others"}</strong></td>
                    <td className="nab-td-num">{l.value}</td>
                    <td><div className="nab-sharecell"><i style={{ width: Math.min(100, l.share || 0) + "%" }} /><span>{l.share}%</span></div></td>
                    <td className="nab-td-num">{l.units}</td>
                  </tr>
                ) : (
                  <tr key={l.rank || i}>
                    <td className="nab-td-rank">{l.rank}</td>
                    <td className="nab-td-name"><strong>{l.name}</strong></td>
                    <td className="nab-td-num">{l.value}</td>
                    <td><div className="nab-sharecell"><i style={{ width: Math.min(100, l.share || 0) + "%" }} /><span>{l.share}%</span></div></td>
                    <td className="nab-td-num">{l.units}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        ) : null}
        {(b.tiers || []).length ? (
        <div className="nab-panel">
          <div className="nab-panel-title">Portfolio Mix</div>
          <div className="nab-mix">
            <div className="nab-donut-wrap">
              {totalSkus ? <div className="nab-donut-center">{totalSkus}<span>Items</span></div> : null}
              <canvas ref={donutRef} />
            </div>
            <div className="nab-legend">
              {(b.tiers || []).map((t, i) => (
                <div className="nab-tier" key={i}>
                  <span className={"nab-dot nab-dot--" + t.tier.toLowerCase()} />
                  <div>
                    <div className="nab-tier-name"><strong>{t.tier}</strong> ({t.band}, {t.meaning})</div>
                    <div className="nab-tier-meta">{t.count} items<br />{t.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        ) : null}
      </div>
      ) : null}

      {((b.standouts || []).length || (b.actions || []).length) ? (
      <div className="nab-grid2">
        {(b.standouts || []).length ? (
        <div className="nab-panel">
          <div className="nab-panel-title">What stands out</div>
          {(b.standouts || []).map((s, i) => (
            <div className="nab-line" key={i}>
              <span className="nab-line-icon"><NabIcon type={s.icon} /></span>
              <div><div className="nab-line-title">{s.title}</div><div className="nab-line-text">{s.text}</div></div>
            </div>
          ))}
        </div>
        ) : null}
        {(b.actions || []).length ? (
        <div className="nab-panel">
          <div className="nab-panel-title">Recommended actions</div>
          {(b.actions || []).map((a, i) => (
            <div className="nab-line" key={i}>
              <span className="nab-line-icon"><NabIcon type={a.icon} /></span>
              <div><div className="nab-line-title">{a.title}</div><div className="nab-line-text">{a.body}</div></div>
            </div>
          ))}
        </div>
        ) : null}
      </div>
      ) : null}

      {(aiHtml || aiGenerating) ? (
      <div className="nab-panel nab-panel--analysis">
        <div className="nab-panel-title">Owzy's Analysis</div>
        {aiGenerating && !aiHtml ? (
          <div className="nab-analysis-loading">
            <div className="nab-analysis-loading-text">Owzy is writing your analysis</div>
            <div className="nab-analysis-loading-bar"><i /></div>
          </div>
        ) : (
          <div className="nab-analysis-body" dangerouslySetInnerHTML={{ __html: aiHtml || "" }} />
        )}
      </div>
      ) : null}

      {(b.explore || []).length ? (
      <div className="nab-panel nab-panel--explore">
        <div className="nab-explore-head"><NabIcon type="search" /> <span>Explore further</span></div>
        <div className="nab-explore">
          {(b.explore || []).map((q, i) => (
            <button className="nab-chip" key={i} type="button" onClick={() => onExplore && onExplore(q)}>
              <span>{q}</span><span className="nab-chip-arrow">→</span>
            </button>
          ))}
        </div>
      </div>
      ) : null}

      <div className="nab-foot">
        <span>{b.footnote}</span>
        <div className="nab-foot-right">
          <button
            type="button"
            className="nab-pdf-btn"
            disabled={pdfBusy}
            onClick={async () => {
              setPdfBusy(true);
              try { await captureReportCardPdf(cardRef.current); }
              finally { setPdfBusy(false); }
            }}
            title="Download this report as a PDF (exact on-screen format)"
          >
            {pdfBusy ? "Preparing…" : "Download PDF"}
          </button>
          <span className="nab-foot-brand">Owzy</span>
        </div>
      </div>
    </div>
  );
}

function DataSnapshotCard({ briefing, aiHtml, aiGenerating, cols, rows, chartSpec, onExportXlsx, onAiReport, onExplore, suggestions, onAsk }) {
  const hasBriefing = !!(briefing && briefing.tiles);
  const noData = (!rows || rows.length === 0);
  return (
    <div className="nac-snapshot-card">
      {hasBriefing ? (
        <OwzyBriefingCard b={briefing} aiHtml={aiHtml} aiGenerating={aiGenerating} onExplore={onExplore} />
      ) : noData ? (
        <div className="nac-nodata-card">
          <div className="nac-nodata-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="7" />
              <line x1="21" y1="21" x2="16.5" y2="16.5" />
              <line x1="8" y1="11" x2="14" y2="11" />
            </svg>
          </div>
          <div className="nac-nodata-title">No data found for this query</div>
          <div className="nac-nodata-sub">
            I couldn’t find any records in your area for this period. Try a different date range, or ask one of these:
          </div>
          {(suggestions || []).length > 0 && (
            <div className="nac-nodata-chips">
              {(suggestions || []).slice(0, 5).map(s => (
                <button
                  key={s}
                  type="button"
                  className="nac-suggest-chip"
                  onClick={() => onAsk && onAsk(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : aiGenerating ? (
        <div className="nab-narrating">
          <div className="nab-narrating-head">
            <span className="nab-narrating-avatar">O</span>
            <div>
              <div className="nab-narrating-title">Owzy's read on your data</div>
              <div className="nab-narrating-steps">
                <span className="nab-step">Data checked ✓</span>
                <span className="nab-narrating-sep">→</span>
                <span className="nab-step nab-step--live">Writing it up…</span>
              </div>
            </div>
          </div>
          <div className="nab-narrating-bar"><i /></div>
        </div>
      ) : (aiHtml ? <div className="nab-analysis-body" dangerouslySetInnerHTML={{ __html: aiHtml }} /> : null)}
      {!noData && cols && cols.length > 0 && (
        <ResultTable
          cols={cols}
          rows={rows}
          truncated={false}
          chartSpec={chartSpec || null}
          onExportXlsx={onExportXlsx}
          onAiReport={onAiReport}
        />
      )}
    </div>
  );
}

function MessageActions({ apiBase, xUid, uUid, staffUid, xBypassUid, conversationId, turnIndex, question, answer, turnId }) {
  const [myRating, setMyRating] = useState(null);
  const [copied, setCopied] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reported, setReported] = useState([]);
  const [pdfBusy, setPdfBusy] = useState(false);

  const REPORT_OPTIONS = [
    { key: "inaccurate_data", label: "Inaccurate data / numbers" },
    { key: "misleading_analysis", label: "Misleading analysis" },
    { key: "irrelevant_answer", label: "Answer not relevant to question" },
    { key: "confusing_formatting", label: "Broken or confusing formatting" },
    { key: "offensive_content", label: "Offensive or inappropriate content" },
    { key: "permission_issue", label: "Showing data I should not see" },
    { key: "other", label: "Other (describe below)" },
  ];

  const authHeaders = () => {
    const h = { "Content-Type": "application/json" };
    if (xUid) h["X-UID"] = xUid;
    if (uUid || staffUid) h["U-UID"] = uUid || staffUid;
    if (staffUid) h["x-staff-uid"] = staffUid;
    if (xBypassUid) h["x-bypass-uid"] = xBypassUid;
    return h;
  };

  useEffect(() => {
    if (!conversationId) return;
    (async () => {
      try {
        const r = await fetch(`${apiBase}/api/chat/feedback?conversation_id=${encodeURIComponent(conversationId)}`, { headers: authHeaders() });
        if (!r.ok) return;
        const d = await r.json();
        const mine = d && d.mine ? d.mine[String(turnIndex)] : null;
        if (mine === "like" || mine === "dislike") setMyRating(mine);
      } catch (_) {}
    })();
  }, [conversationId, turnIndex]);

  async function sendRating(rating) {
    const next = myRating === rating ? null : rating;
    setMyRating(next);
    try {
      await fetch(`${apiBase}/api/chat/feedback`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({
          conversation_id: conversationId || "", turn_index: turnIndex, rating: next,
          question: (question || "").slice(0, 5000), answer: (answer || "").slice(0, 100000),
        }),
      });
    } catch (_) {}
  }

  async function fileReport(reason, details = "") {
    try {
      const r = await fetch(`${apiBase}/api/chat/report`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({
          conversation_id: conversationId || "", turn_index: turnIndex, reason, details,
          question: (question || "").slice(0, 5000), answer: (answer || "").slice(0, 100000),
        }),
      });
      if (r.ok) {
        const d = await r.json();
        if (Array.isArray(d.turn_reasons)) setReported(d.turn_reasons);
      }
    } catch (_) {}
  }

  async function copyAnswer() {
    try {
      await navigator.clipboard.writeText(answer || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch (_) {}
  }

  async function downloadPdf() {
    setPdfBusy(true);
    try {
      const el = turnId != null ? document.querySelector(`[data-turn-body="${turnId}"]`) : null;
      await captureReportCardPdf(el);
    } finally { setPdfBusy(false); }
  }

  const Btn = ({ onClick, title, active, children, disabled }) => (
    <button type="button" className={`nac-ma-btn${active ? " nac-ma-btn--active" : ""}`} onClick={onClick} title={title} disabled={disabled}>
      {children}
    </button>
  );

  return (
    <div className="nac-msg-actions">
      <Btn onClick={copyAnswer} title={copied ? "Copied!" : "Copy"} active={copied}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      </Btn>
      <Btn onClick={() => sendRating("like")} title="Like" active={myRating === "like"}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill={myRating === "like" ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>
      </Btn>
      <Btn onClick={() => sendRating("dislike")} title="Dislike" active={myRating === "dislike"}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill={myRating === "dislike" ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: "rotate(180deg)" }}><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h5a3 3 0 0 1 3 3a3 3 0 0 1-3 3h-2a3 3 0 0 0-3 3Z"/></svg>
      </Btn>
      <div className="nac-ma-pdf-wrap">
        <Btn onClick={() => setReportOpen(v => !v)} title={reported.length ? "Reported" : "Report"} active={reportOpen || reported.length > 0}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill={reported.length ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/></svg>
        </Btn>
        {reportOpen && (
          <div className="nac-report-menu">
            <div className="nac-report-head">
              <span>Report this response</span>
              <button type="button" className="nac-report-close" onClick={() => setReportOpen(false)}>×</button>
            </div>
            <div className="nac-report-options">
              {REPORT_OPTIONS.map(o => reported.includes(o.key) ? (
                <div key={o.key} className="nac-report-done">✓ {o.label}</div>
              ) : (
                <button key={o.key} type="button" onClick={() => { if (o.key === "other") { const d = window.prompt("Describe the issue"); if (d) { fileReport("other", d); setReportOpen(false); } return; } fileReport(o.key); setReportOpen(false); }}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <Btn onClick={downloadPdf} title={pdfBusy ? "Preparing PDF…" : "Download PDF (exact UI)"} disabled={pdfBusy}>
        {pdfBusy ? <span className="nac-ma-spinner" aria-hidden="true" /> : <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>}
      </Btn>
    </div>
  );
}

function ResultTable({ cols, rows, truncated, chartSpec, onExportXlsx, onAiReport }) {
  const [chartType, setChartType] = useState("bar");
  const [showDataLabels, setShowDataLabels] = useState(() => localStorage.getItem("dms_data_labels") === "1");
  const canvasRef = useRef(null);
  const chartRef = useRef(null);
  const { x: defaultX, y: defaultY } = suggestAxes(cols, rows);
  const [xCol, setXCol] = useState(chartSpec?.x && cols.includes(chartSpec.x) ? chartSpec.x : defaultX);
  const [yCol, setYCol] = useState(chartSpec?.y && cols.includes(chartSpec.y) ? chartSpec.y : defaultY);

  const toggleDataLabels = useCallback(() => {
    setShowDataLabels(prev => {
      const next = !prev;
      localStorage.setItem("dms_data_labels", next ? "1" : "0");
      return next;
    });
  }, []);

  useEffect(() => {
    if (chartSpec?.chart_type) {
      const ct = chartSpec.chart_type;
      if (["bar", "line", "pie", "horizontalBar"].includes(ct)) setChartType(ct);
    }
    if (chartSpec?.x && cols.includes(chartSpec.x)) setXCol(chartSpec.x);
    if (chartSpec?.y && cols.includes(chartSpec.y)) setYCol(chartSpec.y);
  }, []);

  const renderChart = useCallback(() => {
    if (!canvasRef.current || !window.Chart) return;
    if (chartRef.current) { try { chartRef.current.destroy(); } catch (_) {} }
    const { labels, values } = chartSeries(rows, xCol, yCol);
    const hasData = labels.length > 0 && values.some(v => v !== null && v !== undefined && v !== 0);
    if (!hasData) return;
    const yLabel = formatColumnLabel(yCol);
    try {
      chartRef.current = buildChartInstance(canvasRef.current, chartType, labels, values, yLabel, showDataLabels, {
        responsive: true,
        height: chartHeightFor(labels, chartType, false),
      });
    } catch (e) { console.error("Chart render error:", e); }
  }, [chartType, xCol, yCol, rows, showDataLabels]);

  useEffect(() => {
    if (!window.Chart) {
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/chart.js";
      script.onload = () => renderChart();
      document.head.appendChild(script);
    } else {
      renderChart();
    }
    return () => { if (chartRef.current) try { chartRef.current.destroy(); } catch (_) {} };
  }, []);

  useEffect(() => {
    if (window.Chart) renderChart();
  }, [chartType, xCol, yCol, showDataLabels]);

  const backendSuggestedX = chartSpec?.suggested_x || chartSpec?.x || defaultX;
  const backendSuggestedY = chartSpec?.suggested_y || chartSpec?.y || defaultY;

  const xSuggestedCols = (chartSpec?.suggested_x_options && chartSpec.suggested_x_options.length > 0)
    ? chartSpec.suggested_x_options.filter(c => cols.includes(c))
    : cols.filter(c => !rows.some(r => isNumber(r[c])));
  const xOtherCols = cols.filter(c => !xSuggestedCols.includes(c));

  const ySuggestedCols = (chartSpec?.suggested_y_options && chartSpec.suggested_y_options.length > 0)
    ? chartSpec.suggested_y_options.filter(c => cols.includes(c))
    : cols.filter(c => rows.some(r => isNumber(r[c])));
  const yOtherCols = cols.filter(c => !ySuggestedCols.includes(c));

  const _chartProbe = chartSeries(rows, xCol, yCol);
  const chartEmpty = !_chartProbe.labels.length ||
    !_chartProbe.values.some(v => v !== null && v !== undefined && v !== 0);

  return (
    <div className="nac-result-wrapper">
      {!showDataLabels ? (
        <div
          className="nac-table-hidden-notice"
          onClick={toggleDataLabels}
          title="Click to turn ON Data Labels and view table"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
          Table Hidden (Data Labels OFF) — Click to view table data
        </div>
      ) : (
        <div className="nac-md-tbl-wrap">
          <table className="nac-md-table">
            <thead>
              <tr>{cols.map(c => <th key={c}>{formatColumnLabel(c)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {cols.map(c => <td key={c}>{displayCellValue(r[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="nac-table-header-row">
        <div className="nac-table-row-count">{rows.length} Records Found</div>
        <div className="nac-table-actions">
          <button className="nac-btn nac-btn--export" onClick={onExportXlsx} title="Export raw data to Excel">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4 }}>
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export Excel
          </button>
          <button className="nac-btn nac-btn--report" onClick={onAiReport} title="Generate AI formatted Excel report">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4 }}>
              <path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z"/>
            </svg>
            AI Excel Report
          </button>
        </div>
      </div>
      {rows.length > 0 && !chartEmpty && (
        <div className="nac-chart-container">
          <div className="nac-chart-toggle">
            <span className="nac-chart-toggle-label">View as</span>
            {[
              { t: "bar",  icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="12" width="4" height="9"/><rect x="10" y="7" width="4" height="14"/><rect x="17" y="3" width="4" height="18"/></svg> },
              { t: "line", icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> },
              { t: "pie",  icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg> },
            ].map(({ t, icon }) => (
              <button
                key={t}
                className={`nac-ct-btn${(chartType === t || (t === "bar" && chartType === "horizontalBar")) ? " nac-ct-btn--active" : ""}`}
                onClick={() => setChartType(t)}
              >
                {icon} {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
            <button
              className={`nac-ct-btn${showDataLabels ? " nac-ct-btn--active" : ""}`}
              onClick={toggleDataLabels}
              title="Toggle Data Labels ON/OFF across graph"
              style={{ marginLeft: 6 }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4 }}>
                <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
                <line x1="7" y1="7" x2="7.01" y2="7" />
              </svg>
              Data Labels: {showDataLabels ? "ON" : "OFF"}
            </button>

            <div className="nac-chart-axes">
              <div className="nac-axis-select-wrap" title="X-Axis (Category/Label)">
                <span className="nac-axis-tag nac-axis-tag--x">X</span>
                <select className="nac-chart-select" value={xCol} onChange={e => setXCol(e.target.value)}>
                  {xSuggestedCols.length > 0 && (
                    <optgroup label="Suggested by Backend (Categories)">
                      {xSuggestedCols.map(c => (
                        <option key={c} value={c}>{formatColumnLabel(c)}{c === backendSuggestedX ? " ★" : ""}</option>
                      ))}
                    </optgroup>
                  )}
                  {xOtherCols.length > 0 && (
                    <optgroup label="Other Columns">
                      {xOtherCols.map(c => (
                        <option key={c} value={c}>{formatColumnLabel(c)}{c === backendSuggestedX ? " ★" : ""}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>

              <div className="nac-axis-select-wrap" title="Y-Axis (Metric/Value)">
                <span className="nac-axis-tag nac-axis-tag--y">Y</span>
                <select className="nac-chart-select" value={yCol} onChange={e => setYCol(e.target.value)}>
                  {ySuggestedCols.length > 0 && (
                    <optgroup label="Suggested by Backend (Metrics)">
                      {ySuggestedCols.map(c => (
                        <option key={c} value={c}>{formatColumnLabel(c)}{c === backendSuggestedY ? " ★" : ""}</option>
                      ))}
                    </optgroup>
                  )}
                  {yOtherCols.length > 0 && (
                    <optgroup label="Other Columns">
                      {yOtherCols.map(c => (
                        <option key={c} value={c}>{formatColumnLabel(c)}{c === backendSuggestedY ? " ★" : ""}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>
            </div>
          </div>
          <div className="nac-chart-canvas-wrap" style={{ height: chartHeightFor(_chartProbe.labels, chartType, false) }}>
            <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
          </div>
        </div>
      )}
    </div>
  );
}

const AI_REPORT_CHIPS = [
  { label: "📊 Summary", sub: "Group & sum totals", prompt: "Group by the main category column and show sum and average totals for all numeric columns" },
  { label: "📅 By Period", sub: "Group by date", prompt: "Group by date or time column and show totals per period, sorted by date" },
  { label: "🎯 KPI", sub: "Totals & averages", prompt: "Show overall sum, average, min and max for all numeric columns as a KPI summary" },
  { label: "🔥 Highlights", sub: "Color scale ranking", prompt: "Sort by the main value column descending and apply color scale highlighting from red to green" },
];

function NacModal({ title, message, showInput, inputPlaceholder, showReportChips, onConfirm, onCancel }) {
  const [inputVal, setInputVal] = useState("");
  return (
    <div className="nac-modal-overlay" onClick={onCancel}>
      <div className="nac-modal" onClick={e => e.stopPropagation()}>
        <div className="nac-modal-title">{title}</div>
        <div className="nac-modal-message">{message}</div>
        {showInput && (
          <input
            className="nac-modal-input"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            placeholder={inputPlaceholder || ""}
            autoFocus
          />
        )}
        {showReportChips && (
          <div className="nac-modal-chips">
            {AI_REPORT_CHIPS.map(c => (
              <button key={c.label} className="nac-modal-chip" onClick={() => setInputVal(c.prompt)}>
                <span className="nac-modal-chip-title">{c.label}</span>
                <span className="nac-modal-chip-sub">{c.sub}</span>
              </button>
            ))}
          </div>
        )}
        <div className="nac-modal-actions">
          <button className="nac-modal-btn nac-modal-btn--cancel" onClick={onCancel}>Cancel</button>
          <button className="nac-modal-btn nac-modal-btn--confirm" onClick={() => onConfirm(showInput ? inputVal : true)}>
            {showInput ? "Submit" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}


const INJECTED_CSS = `
/* Native AI Chat Styles */

/* ── Native Modal ───────────────────────────────────────────────────── */

.nac-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: nac-modal-fadein 0.2s ease-out;
}

@keyframes nac-modal-fadein {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.nac-modal {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
  padding: 24px;
  width: 340px;
  max-width: 90vw;
  animation: nac-modal-pop 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes nac-modal-pop {
  from { transform: scale(0.9); opacity: 0; }
  to   { transform: scale(1); opacity: 1; }
}

.nac-modal-title {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 8px;
}

.nac-modal-message {
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
  margin-bottom: 16px;
}

.nac-modal-input {
  width: 100%;
  padding: 10px 12px;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  font-size: 13px;
  color: #1e293b;
  outline: none;
  margin-bottom: 16px;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.nac-modal-input:focus {
  border-color: #6366f1;
}

.nac-modal-input::placeholder {
  color: #94a3b8;
}

.nac-modal-chips {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 16px;
}

.nac-modal-chip {
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}

.nac-modal-chip:hover {
  border-color: #4f46e5;
  background: #eef2ff;
}

.nac-modal-chip-title {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: #1e293b;
}

.nac-modal-chip-sub {
  display: block;
  font-size: 10px;
  color: #94a3b8;
  margin-top: 2px;
}

.nac-modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.nac-modal-btn {
  padding: 8px 20px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
}

.nac-modal-btn:active {
  transform: scale(0.97);
}

.nac-modal-btn--cancel {
  background: #f1f5f9;
  color: #475569;
}

.nac-modal-btn--cancel:hover {
  background: #e2e8f0;
}

.nac-modal-btn--confirm {
  background: #4f46e5;
  color: #fff;
}

.nac-modal-btn--confirm:hover {
  background: #4338ca;
}
.nac-container {
  display: flex;
  flex-direction: row;
  height: 100%;
  background: #fff;
  font-family: 'Segoe UI', Inter, Arial, sans-serif;
  position: relative;
  overflow: hidden;
}

.nac-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
  overflow: hidden;
}

/* ── Sidebar ────────────────────────────────────────────────────────── */

.nac-sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 39;
}

.nac-sidebar {
  width: 240px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 40;
  transform: translateX(-100%);
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  transition: transform 0.25s ease;
}

.nac-sidebar--open {
  transform: translateX(0);
}

.nac-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 6px;
}

.nac-sidebar-title {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.nac-sidebar-actions {
  display: flex;
  gap: 4px;
}

.nac-sidebar-icon-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}

.nac-sidebar-icon-btn:hover {
  background: #e2e8f0;
}

.nac-history-search {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 4px 10px 8px;
  padding: 7px 9px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #94a3b8;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.nac-history-search:focus-within {
  border-color: #93c5fd;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.08);
}

.nac-history-search input {
  min-width: 0;
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: #334155;
  font: inherit;
  font-size: 11px;
}

.nac-history-search input::placeholder { color: #94a3b8; }

.nac-history-search-clear {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 16px;
  line-height: 12px;
  padding: 0;
}

.nac-history-search-clear:hover { color: #334155; }

.nac-sidebar-clear {
  margin: 4px 12px 8px;
  padding: 5px 0;
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  background: none;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.nac-sidebar-clear:hover {
  color: #dc2626;
  background: #fef2f2;
}

.nac-sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nac-sidebar-empty {
  text-align: center;
  padding: 24px 8px;
  font-size: 11px;
  color: #94a3b8;
}

.nac-sidebar-item {
  padding: 8px 10px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.nac-sidebar-item:hover {
  border-color: #a5b4fc;
  box-shadow: 0 1px 4px rgba(99,102,241,0.08);
}

.nac-sidebar-item-q {
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.nac-sidebar-item-date {
  font-size: 10px;
  color: #94a3b8;
  margin-top: 3px;
}

.nac-sidebar-item-del {
  margin-top: 4px;
  width: 100%;
  padding: 3px 0;
  font-size: 10px;
  color: #64748b;
  background: none;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.nac-sidebar-item-del:hover {
  color: #dc2626;
  background: #fef2f2;
}

.nac-sidebar-footer {
  padding: 8px;
  border-top: 1px solid #e2e8f0;
}

.nac-sidebar-new-btn {
  width: 100%;
  padding: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(30, 58, 138, 0.3);
  transition: opacity 0.15s;
}

.nac-sidebar-new-btn:hover {
  opacity: 0.9;
}

.nac-sidebar-new-btn:hover {
  background: #4338ca;
}

/* Toolbar (matches AIChat.tsx design) */
.nac-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid rgba(37, 99, 235, 0.13);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.nac-toolbar-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 180px;
}

.nac-tb-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg, #1e40af, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nac-tb-title {
  font-size: 13.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.nac-tb-status {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: #64748b;
  margin-top: 1px;
}

.nac-toolbar-btns {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.nac-tbtn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  background: #f0f5ff;
  border: 1.5px solid rgba(37, 99, 235, 0.13);
  color: #1e40af;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
  white-space: nowrap;
}

.nac-tbtn:hover {
  background: #dbeafe;
  border-color: #2563eb;
}

.nac-tbtn--active {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
}

.nac-tbtn--active:hover {
  background: #1d4ed8;
  border-color: #1d4ed8;
}

/* Header (legacy — kept for backwards compat, not actively used) */
.nac-header-legacy {
  padding: 12px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.nac-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.nac-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nac-logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}

.nac-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.2;
}

.nac-subtitle {
  font-size: 11px;
  color: #64748b;
  margin-top: 1px;
}

.nac-status {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.nac-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.nac-status-dot--green { background: #34d399; }
.nac-status-dot--amber { background: #818cf8; }
.nac-status-dot--gray { background: #94a3b8; }

.nac-status-text {
  font-size: 10px;
  color: #64748b;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nac-container {
  display: flex;
  flex-direction: row;
  height: 100%;
  background: #f8fafc;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  position: relative;
  overflow: hidden;
}

/* Chat Area */
.nac-chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 18px 20px;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  min-height: 0;
}

.nac-chat-area::-webkit-scrollbar {
  width: 6px;
}

.nac-chat-area::-webkit-scrollbar-track {
  background: transparent;
}

.nac-chat-area::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.nac-messages {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Chat Bubbles & Animations */
.nac-bubble {
  display: flex;
  align-items: flex-start;
  animation: nac-msg-appear 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}

.nac-msg-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.nac-msg-avatar--assistant {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #1d4ed8 100%);
  box-shadow: 0 3px 10px rgba(30, 58, 138, 0.35);
  margin-right: 10px;
}

.nac-msg-avatar--user {
  background: linear-gradient(135deg, #334155 0%, #0f172a 100%);
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.25);
  margin-left: 10px;
}

.nac-msg-avatar--thinking {
  animation: nac-avatar-pulse 1.8s infinite ease-in-out;
}

@keyframes nac-avatar-pulse {
  0%, 100% { transform: scale(1); box-shadow: 0 3px 10px rgba(30, 58, 138, 0.35); }
  50% { transform: scale(1.08); box-shadow: 0 4px 16px rgba(37, 99, 235, 0.6); }
}

/* ── Interactive Thinking State ─────────────────────────────────────── */
.nac-thinking-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 240px;
  padding: 4px 0;
}

.nac-thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 500;
  color: #1e3a8a;
}

.nac-thinking-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.7);
  animation: nac-pulse-ring 1.4s infinite cubic-bezier(0.66, 0, 0, 1);
  flex-shrink: 0;
}

@keyframes nac-pulse-ring {
  0% {
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.7);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(37, 99, 235, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0);
  }
}

.nac-thinking-step-text {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 13px;
  font-weight: 500;
  color: #1e3a8a;
  animation: nac-text-fade 0.4s ease-out;
  white-space: nowrap;
}

@keyframes nac-text-fade {
  from { opacity: 0; transform: translateY(3px); }
  to   { opacity: 1; transform: translateY(0); }
}

.nac-thinking-bar-wrap {
  width: 100%;
  height: 3px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.nac-thinking-bar-fill {
  width: 45%;
  height: 100%;
  background: linear-gradient(90deg, #1e3a8a, #2563eb, #60a5fa);
  border-radius: 4px;
  position: absolute;
  animation: nac-shimmer-slide 1.6s infinite ease-in-out;
}

@keyframes nac-shimmer-slide {
  0%   { left: -45%; }
  50%  { left: 40%; }
  100% { left: 105%; }
}

@keyframes nac-msg-appear {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* Markdown content inside chat bubbles */
.nac-md-content { font-size: 13px; line-height: 1.6; color: #1e293b; }
.nac-md-content p { margin: 0 0 8px; }
.nac-md-content p:last-child { margin-bottom: 0; }
.nac-md-content strong { font-weight: 700; color: #0f172a; }
.nac-md-h1 { font-size: 13.5px; font-weight: 700; color: #1e3a8a; text-transform: uppercase; letter-spacing: 0.05em; margin: 12px 0 6px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; }
.nac-md-h2 { font-size: 13px; font-weight: 600; color: #1e293b; margin: 10px 0 5px; }
.nac-md-bullets { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.nac-md-bullets li { padding-left: 14px; position: relative; font-size: 12.5px; }
.nac-md-bullets li::before { content: "▸"; position: absolute; left: 0; color: #2563eb; font-size: 11px; top: 2px; }
.nac-md-code { background: #eff6ff; padding: 2px 6px; border-radius: 5px; font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 11.5px; color: #1d4ed8; border: 1px solid rgba(37, 99, 235, 0.18); }
.nac-md-tbl-wrap { margin: 8px 0; overflow-x: auto; border-radius: 10px; border: 1px solid #e2e8f0; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04); }
.nac-md-table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 260px; }
.nac-md-table thead tr { background: linear-gradient(135deg, #1e40af, #2563eb); }
.nac-md-table thead th { padding: 8px 12px; color: #fff; font-weight: 600; text-align: left; font-size: 11.5px; white-space: nowrap; letter-spacing: 0.02em; }
.nac-md-table tbody tr:nth-child(even) { background: #f8fafc; }
.nac-md-table tbody tr { border-bottom: 1px solid #f1f5f9; transition: background 0.12s; }
.nac-md-table tbody tr:hover { background: #eff6ff; }
.nac-table-hidden-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(37, 99, 235, 0.06);
  border: 1.5px dashed rgba(37, 99, 235, 0.3);
  border-radius: 10px;
  color: #1e40af;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  margin: 10px 0;
  transition: all 0.18s ease;
}

.nac-table-hidden-notice:hover {
  background: rgba(37, 99, 235, 0.12);
  border-color: #2563eb;
  color: #1d4ed8;
  transform: translateY(-1px);
}

.nac-table-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  margin-bottom: 12px;
  gap: 12px;
}

.nac-table-row-count {
  font-size: 11.5px;
  font-weight: 600;
  color: #475569;
  background: #f1f5f9;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.nac-table-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nac-btn--export {
  background: #ffffff;
  color: #1e3a8a;
  border: 1px solid #cbd5e1;
  font-weight: 600;
  font-size: 11.5px;
  padding: 5px 12px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  transition: all 0.15s ease;
}

.nac-btn--export:hover {
  background: #f8fafc;
  color: #1d4ed8;
  border-color: #93c5fd;
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(37, 99, 235, 0.12);
}

.nac-btn--report {
  background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.15);
  font-weight: 600;
  font-size: 11.5px;
  padding: 5px 12px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(30, 58, 138, 0.28);
  transition: all 0.15s ease;
}

.nac-btn--report:hover {
  background: linear-gradient(135deg, #1e40af 0%, #2563eb 100%);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
}

.nac-bubble--user {
  justify-content: flex-end;
}

.nac-bubble--assistant {
  justify-content: flex-start;
}

.nac-bubble-content {
  max-width: 85%;
  border-radius: 18px;
  padding: 12px 16px;
  border: 1px solid;
  transition: box-shadow 0.2s, transform 0.15s;
}

.nac-bubble-content--user {
  background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%);
  color: #fff;
  border-color: transparent;
  border-bottom-right-radius: 4px;
  box-shadow: 0 4px 14px rgba(30, 58, 138, 0.32);
}

.nac-bubble-content--assistant {
  background: #ffffff;
  color: #1e293b;
  border-color: rgba(226, 232, 240, 0.9);
  border-top-left-radius: 4px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
  position: relative;
}

.nac-bubble-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.nac-bubble-title--user {
  color: rgba(255, 255, 255, 0.85);
}

.nac-bubble-title--assistant {
  color: #1e3a8a;
}

.nac-bubble-body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 13.5px;
  line-height: 1.6;
  color: inherit;
  letter-spacing: -0.005em;
  word-break: break-word;
}

/* Sidebar date group header */
.nac-sidebar-date-group {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: .05em;
  padding: 10px 10px 4px;
  display: flex;
  gap: 4px;
  align-items: center;
}
.nac-sidebar-date-group span { color: #cbd5e1; font-weight: 400; }

/* Sidebar item action buttons (rename/delete) */
.nac-sidebar-item { position: relative; }
.nac-sidebar-item-actions {
  display: none;
  gap: 2px;
  margin-top: 4px;
  align-items: center;
}
.nac-sidebar-item:hover .nac-sidebar-item-actions { display: flex; }

.nac-sidebar-act-btn {
  background: none;
  border: none;
  padding: 4px;
  cursor: pointer;
  color: #64748b;
  border-radius: 5px;
  display: flex;
  align-items: center;
  transition: background .12s, color .12s;
}
.nac-sidebar-act-btn:hover { background: #dbeafe; color: #2563eb; }
.nac-sidebar-act-del:hover { background: #fee2e2 !important; color: #dc2626 !important; }

/* Rename inline input */
.nac-sidebar-rename-input {
  width: 100%;
  border: 1.5px solid #3b82f6;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11.5px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  margin-bottom: 3px;
}

/* Table hidden notice (matches index.html) */
.nac-tbl-hidden-notice {
  display: none;
  background: #f0f5ff;
  border: 1px solid rgba(37,99,235,.15);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 11px;
  color: #475569;
  cursor: pointer;
  align-items: center;
  gap: 6px;
  margin: 4px 0;
}
.nac-tbl-hidden-notice strong { color: #2563eb; text-decoration: underline; }
.data-tables-hidden .nac-tbl-hidden-notice { display: flex; }
.data-tables-hidden .nac-md-tbl-wrap { display: none; }

/* Lang Pref modal tabs — Input (voice) vs Output (AI answers) */
.nac-lpm-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  padding: 3px;
  background: #f1f5f9;
  border-radius: 10px;
}
.nac-lpm-tab {
  flex: 1;
  padding: 7px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s;
  font-family: inherit;
}
.nac-lpm-tab:hover { color: #334155; }
.nac-lpm-tab--active {
  background: #fff;
  color: #4338ca;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

/* Lang Pref grid */
.nac-lpm-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin-bottom: 16px;
}
.nac-lpm-chip {
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 8px;
  padding: 7px 6px;
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  transition: all .15s;
  font-family: inherit;
  text-align: center;
}
.nac-lpm-chip:hover { border-color: #4f46e5; background: #eef2ff; }
.nac-lpm-chip--active { border-color: #4f46e5; background: #4f46e5; color: #fff; }


.nac-bubble-title {
  font-size: 10px;
  font-weight: 500;
}

.nac-bubble-title--user {
  color: rgba(224, 231, 255, 0.85);
}

.nac-bubble-title--assistant {
  color: #64748b;
}

.nac-bubble-body {
  margin-top: 4px;
  font-size: 12.5px;
  white-space: pre-wrap;
  line-height: 1.5;
  word-break: break-word;
}

.nac-bubble-extra {
  margin-top: 8px;
}

/* Code Block */
.nac-code-label {
  font-size: 10px;
  color: #64748b;
  margin-bottom: 4px;
}

.nac-code-pre {
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 11px;
  overflow: auto;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 8px 10px;
  color: #334155;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Result Table */
.nac-table-info {
  font-size: 10px;
  color: #475569;
  margin-bottom: 6px;
}

.nac-table-wrap {
  overflow: auto;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  max-height: 200px;
}

.nac-table {
  width: 100%;
  font-size: 11px;
  border-collapse: collapse;
}

/* Multi-result grid */
.nac-multi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.nac-multi-card {
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  padding: 10px;
}

.nac-multi-card-title {
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.nac-table th {
  text-align: left;
  padding: 5px 8px;
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
  position: sticky;
  top: 0;
  z-index: 1;
}

.nac-table td {
  padding: 4px 8px;
  white-space: nowrap;
  border-top: 1px solid #f1f5f9;
  color: #334155;
}

.nac-table tr:hover td {
  background: #f8fafc;
}

.nac-table-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.nac-btn {
  border: none;
  border-radius: 6px;
  font-weight: 600;
  font-size: 11px;
  padding: 5px 10px;
  cursor: pointer;
  transition: opacity 0.15s;
}

.nac-btn:hover {
  opacity: 0.85;
}

.nac-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nac-btn--export {
  background: #6ee7b7;
  color: #064e3b;
}

.nac-btn--report {
  background: #f0abfc;
  color: #581c87;
}

.nac-btn--primary {
  background: #4f46e5;
  color: #fff;
}

/* Chart */
.nac-chart-container {
  margin-top: 10px;
  border-radius: 10px;
  background: #f0f5ff;
  border: 1px solid rgba(37, 99, 235, 0.12);
  padding: 14px;
}

.nac-chart-header {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: flex-end;
  justify-content: space-between;
}

.nac-chart-title {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
}

.nac-chart-subtitle {
  font-size: 10px;
  color: #64748b;
  margin-top: 2px;
}

.nac-chart-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* Chart type pill toggle (matches index.html / app.js sfa-ct-btn) */
.nac-chart-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.nac-chart-toggle-label {
  font-size: 10.5px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: .06em;
  margin-right: 4px;
  white-space: nowrap;
}

.nac-ct-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 12px;
  border-radius: 20px;
  border: 1.5px solid rgba(37, 99, 235, 0.2);
  background: #f8faff;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}

.nac-ct-btn:hover {
  background: #dbeafe;
  border-color: #2563eb;
}

.nac-ct-btn--active {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.nac-chart-axes {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  flex-wrap: wrap;
}

.nac-axis-select-wrap {
  display: inline-flex;
  align-items: center;
  background: #ffffff;
  border: 1.5px solid rgba(37, 99, 235, 0.2);
  border-radius: 20px;
  padding: 2px 8px 2px 4px;
  transition: all 0.15s ease;
}

.nac-axis-select-wrap:hover {
  background: #f0f7ff;
  border-color: #2563eb;
}

.nac-axis-tag {
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 12px;
  line-height: 1;
  text-transform: uppercase;
  margin-right: 4px;
}

.nac-axis-tag--x {
  background: #e0e7ff;
  color: #4338ca;
}

.nac-axis-tag--y {
  background: #dcfce7;
  color: #15803d;
}

.nac-chart-select {
  border: none;
  background: transparent;
  padding: 2px 0;
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  outline: none;
  cursor: pointer;
  max-width: 140px;
}

.nac-chart-select optgroup {
  font-weight: 700;
  color: #64748b;
  font-size: 10.5px;
}

.nac-chart-canvas-wrap {
  margin: 8px auto 0;
  width: 100%;
  max-width: 820px;
  position: relative;
  border-radius: 10px;
  background: #fff;
  padding: 8px;
  box-sizing: border-box;
}

.nac-chart-canvas-wrap canvas {
  width: 100% !important;
  height: 100% !important;
  max-width: 100% !important;
  max-height: 100% !important;
}

/* Input Area */
.nac-input-area {
  padding: 10px 16px 12px;
  background: #fff;
  border-top: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.nac-header-action {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
  margin-left: 4px;
}

.nac-header-action:hover {
  background: #e2e8f0;
  color: #4f46e5;
}

.nac-suggestions {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 0 0 8px;
  scrollbar-width: none;
}

.nac-suggestions::-webkit-scrollbar { display: none; }

.nac-suggest-chip {
  background: #eef2ff;
  border: 1px solid rgba(99, 102, 241, 0.2);
  color: #4338ca;
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}

.nac-suggest-chip:hover {
  background: #dbeafe;
  border-color: #6366f1;
  color: #4f46e5;
}

.nac-form {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nac-input-wrap {
  flex: 1;
  background: #fff;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  padding: 8px 12px;
  transition: border-color 0.2s;
}

.nac-input-wrap:focus-within {
  border-color: #6366f1;
}

.nac-input {
  width: 100%;
  border: none;
  outline: none;
  font-size: 12.5px;
  background: transparent;
  color: #1e293b;
}

.nac-input::placeholder {
  color: #94a3b8;
}

.nac-btn-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: opacity 0.15s;
  position: relative;
}

.nac-btn-icon:hover {
  opacity: 0.88;
}

.nac-btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nac-btn-send {
  background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 100%);
  box-shadow: 0 3px 10px rgba(30, 58, 138, 0.4);
}

/* ── Modern Mic Button ──────────────────────────────────────────────── */

.nac-btn-voice {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #1d4ed8 100%);
  box-shadow: 0 3px 10px rgba(30, 58, 138, 0.4);
  position: relative;
  overflow: visible;
}

.nac-btn-voice::before {
  content: "";
  position: absolute;
  inset: -2px;
  border-radius: 12px;
  background: linear-gradient(135deg, #1e3a8a, #1d4ed8, #2563eb);
  z-index: -1;
  opacity: 0;
  transition: opacity 0.3s;
}


.nac-btn-voice:hover::before {
  opacity: 1;
}

.nac-btn-voice--recording {
  background: linear-gradient(135deg, #b91c1c 0%, #ef4444 100%) !important;
  animation: nac-voice-btn-pulse 1.2s infinite;
}

/* ── Per-message "read aloud" button (Web Speech API, client-side only) ──── */

.nac-btn-speak {
  position: absolute;
  bottom: -8px;
  right: -8px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 1px solid rgba(30, 58, 138, 0.18);
  background: linear-gradient(135deg, #ffffff, #f1f5f9);
  color: #1d4ed8;
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.12);
  transition: transform 0.15s, box-shadow 0.15s;
  padding: 0;
  z-index: 1;
}

.nac-btn-speak:hover {
  transform: scale(1.08);
}

.nac-btn-speak--active {
  background: linear-gradient(135deg, #b91c1c, #ef4444);
  color: #fff;
  border-color: transparent;
}

@keyframes nac-voice-btn-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
  70%  { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}

.nac-mic-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

/* Pulsing rings on the mic button */
.nac-mic-ring {
  position: absolute;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1.5px solid rgba(255,255,255,0.35);
  animation: nac-mic-ring-pulse 2.5s ease-out infinite;
  pointer-events: none;
}

.nac-mic-ring:nth-child(2) { animation-delay: 0.8s; }
.nac-mic-ring:nth-child(3) { animation-delay: 1.6s; }

@keyframes nac-mic-ring-pulse {
  0%   { transform: scale(0.8); opacity: 0.8; }
  100% { transform: scale(2.2); opacity: 0; }
}

/* ── Voice Visualizer Overlay — Fog + Bubbles ──────────────────────── */

.nac-voice-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  animation: nac-vo-fadein 0.4s ease-out;
}

@keyframes nac-vo-fadein {
  from { opacity: 0; }
  to   { opacity: 1; }
}

/* Fog background layers */
.nac-fog {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.nac-fog-layer {
  position: absolute;
  inset: -50%;
  width: 200%;
  height: 200%;
  border-radius: 40%;
}

.nac-fog-layer--1 {
  background: radial-gradient(ellipse at 30% 40%, rgba(99,102,241,0.35) 0%, rgba(139,92,246,0.15) 40%, transparent 70%);
  animation: nac-fog-drift-1 8s ease-in-out infinite;
}

.nac-fog-layer--2 {
  background: radial-gradient(ellipse at 70% 60%, rgba(168,85,247,0.3) 0%, rgba(56,189,248,0.12) 45%, transparent 70%);
  animation: nac-fog-drift-2 10s ease-in-out infinite;
}

.nac-fog-layer--3 {
  background: radial-gradient(ellipse at 50% 30%, rgba(244,114,182,0.2) 0%, rgba(192,132,252,0.1) 50%, transparent 70%);
  animation: nac-fog-drift-3 12s ease-in-out infinite;
}

@keyframes nac-fog-drift-1 {
  0%, 100% { transform: translate(0, 0) rotate(0deg) scale(1); }
  33%      { transform: translate(8%, -6%) rotate(3deg) scale(1.05); }
  66%      { transform: translate(-5%, 4%) rotate(-2deg) scale(0.97); }
}

@keyframes nac-fog-drift-2 {
  0%, 100% { transform: translate(0, 0) rotate(0deg) scale(1); }
  40%      { transform: translate(-10%, 5%) rotate(-4deg) scale(1.08); }
  70%      { transform: translate(6%, -8%) rotate(2deg) scale(0.95); }
}

@keyframes nac-fog-drift-3 {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  50%      { transform: translate(5%, 7%) rotate(5deg); }
}

/* Dark base behind fog */
.nac-voice-overlay::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(160deg, #080515 0%, #0d0b20 30%, #0a0d1f 60%, #070512 100%);
  z-index: 0;
}

/* ── Floating Bubbles ──────────────────────────────────────────────── */

.nac-bubbles-container {
  position: relative;
  width: 220px;
  height: 140px;
  z-index: 2;
}

.nac-bubble-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(1px);
  animation: nac-bubble-float ease-in-out infinite;
}

/* Each bubble: unique size, color, position, timing */
.nac-bubble-orb--1 {
  width: 50px; height: 50px;
  background: radial-gradient(circle at 35% 35%, rgba(244,114,182,0.9), rgba(244,114,182,0.15));
  left: 10%; top: 30%;
  animation-duration: 3.2s;
  animation-delay: 0s;
}

.nac-bubble-orb--2 {
  width: 38px; height: 38px;
  background: radial-gradient(circle at 35% 35%, rgba(167,139,250,0.9), rgba(167,139,250,0.15));
  left: 30%; top: 10%;
  animation-duration: 2.8s;
  animation-delay: 0.3s;
}

.nac-bubble-orb--3 {
  width: 58px; height: 58px;
  background: radial-gradient(circle at 35% 35%, rgba(99,102,241,0.85), rgba(99,102,241,0.12));
  left: 45%; top: 35%;
  animation-duration: 3.6s;
  animation-delay: 0.6s;
}

.nac-bubble-orb--4 {
  width: 32px; height: 32px;
  background: radial-gradient(circle at 35% 35%, rgba(56,189,248,0.9), rgba(56,189,248,0.15));
  left: 68%; top: 15%;
  animation-duration: 2.5s;
  animation-delay: 0.15s;
}

.nac-bubble-orb--5 {
  width: 44px; height: 44px;
  background: radial-gradient(circle at 35% 35%, rgba(45,212,191,0.85), rgba(45,212,191,0.12));
  left: 75%; top: 45%;
  animation-duration: 3.0s;
  animation-delay: 0.45s;
}

.nac-bubble-orb--6 {
  width: 26px; height: 26px;
  background: radial-gradient(circle at 35% 35%, rgba(232,121,249,0.9), rgba(232,121,249,0.15));
  left: 18%; top: 65%;
  animation-duration: 2.6s;
  animation-delay: 0.7s;
}

.nac-bubble-orb--7 {
  width: 36px; height: 36px;
  background: radial-gradient(circle at 35% 35%, rgba(129, 140, 248,0.8), rgba(129, 140, 248,0.12));
  left: 55%; top: 68%;
  animation-duration: 3.4s;
  animation-delay: 0.2s;
}

@keyframes nac-bubble-float {
  0%   { transform: translateY(0) scale(1);   opacity: 0.7; }
  25%  { transform: translateY(-18px) scale(1.15); opacity: 1; }
  50%  { transform: translateY(-8px) scale(0.95); opacity: 0.85; }
  75%  { transform: translateY(-22px) scale(1.1);  opacity: 0.95; }
  100% { transform: translateY(0) scale(1);   opacity: 0.7; }
}

/* Bubble wave wobble on top of float */
.nac-bubble-orb::after {
  content: "";
  position: absolute;
  inset: 15%;
  border-radius: 50%;
  background: rgba(255,255,255,0.12);
  animation: nac-bubble-wobble 2s ease-in-out infinite;
}

@keyframes nac-bubble-wobble {
  0%, 100% { transform: translate(0, 0) rotate(0deg); border-radius: 50%; }
  25%      { transform: translate(2px, -2px) rotate(5deg); border-radius: 48% 52% 50% 50%; }
  50%      { transform: translate(-1px, 1px) rotate(-3deg); border-radius: 52% 48% 48% 52%; }
  75%      { transform: translate(1px, 2px) rotate(4deg); border-radius: 50% 50% 52% 48%; }
}

/* ── Labels & Stop (overlay) ───────────────────────────────────────── */

.nac-voice-label {
  font-size: 15px;
  font-weight: 600;
  color: rgba(255,255,255,0.9);
  letter-spacing: 0.8px;
  z-index: 2;
  text-shadow: 0 2px 12px rgba(99,102,241,0.4);
}

.nac-voice-sublabel {
  font-size: 11px;
  color: rgba(255,255,255,0.4);
  margin-top: -12px;
  z-index: 2;
}

.nac-voice-stop {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.15);
  background: rgba(239,68,68,0.15);
  backdrop-filter: blur(12px);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.25s, background 0.25s, border-color 0.25s;
  z-index: 2;
  position: relative;
}

.nac-voice-stop::before {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 1.5px solid rgba(239,68,68,0.3);
  animation: nac-stop-ring 2s ease-out infinite;
}

@keyframes nac-stop-ring {
  0%   { transform: scale(1); opacity: 0.6; }
  100% { transform: scale(1.5); opacity: 0; }
}

.nac-voice-stop:hover {
  transform: scale(1.12);
  background: rgba(239,68,68,0.6);
  border-color: rgba(239,68,68,0.5);
}

/* Processing state — calmer bubbles */
.nac-voice-overlay--processing .nac-bubble-orb {
  animation-duration: 5s !important;
  opacity: 0.4;
}

.nac-voice-overlay--processing .nac-fog-layer {
  animation-duration: 16s !important;
  opacity: 0.5;
}

/* Connecting state — gentle pulse while mic initializes */
.nac-voice-overlay--connecting .nac-bubble-orb {
  animation-duration: 4s !important;
  opacity: 0.35;
}

.nac-voice-overlay--connecting .nac-fog-layer {
  animation-duration: 14s !important;
  opacity: 0.4;
}

/* Bottom controls row */
.nac-voice-bottom {
  display: flex;
  align-items: center;
  gap: 16px;
  z-index: 2;
}

/* Back to text button */
.nac-voice-back {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  border-radius: 24px;
  border: 1.5px solid rgba(255,255,255,0.15);
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(10px);
  color: rgba(255,255,255,0.8);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, transform 0.2s;
}

.nac-voice-back:hover {
  background: rgba(255,255,255,0.12);
  border-color: rgba(255,255,255,0.3);
  transform: scale(1.04);
}

.nac-voice-status {
  font-size: 10px;
  color: #64748b;
  white-space: nowrap;
}

.nac-hint {
  margin-top: 6px;
  font-size: 10px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Loading dots animation */
.nac-loading {
  display: inline-flex;
  gap: 3px;
  align-items: center;
}

.nac-loading-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #6366f1;
  animation: nac-bounce 1.2s ease-in-out infinite;
}

.nac-loading-dot:nth-child(2) { animation-delay: 0.15s; }
.nac-loading-dot:nth-child(3) { animation-delay: 0.3s; }

@keyframes nac-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* Batch mode panel */
.nac-batch-panel {
  padding: 12px 16px;
  background: #f7f9fc;
  border-bottom: 1px solid rgba(124, 58, 237, 0.2);
  flex-shrink: 0;
}

.nac-batch-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.nac-batch-title {
  font-size: 12px;
  font-weight: 700;
  color: #4338ca;
  flex: 1;
}

.nac-batch-hint {
  font-size: 10px;
  color: #6366f1;
}

.nac-batch-close {
  background: none;
  border: none;
  font-size: 16px;
  color: #6366f1;
  cursor: pointer;
  padding: 0 4px;
}

.nac-batch-textarea {
  width: 100%;
  border: 1.5px solid rgba(124, 58, 237, 0.25);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 11.5px;
  font-family: inherit;
  resize: vertical;
  background: #fff;
  outline: none;
  min-height: 70px;
  box-sizing: border-box;
}

.nac-batch-textarea:focus {
  border-color: #7c3aed;
}

.nac-batch-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.nac-batch-prog {
  flex: 1;
  font-size: 10.5px;
  color: #4338ca;
}

.nac-batch-prog--running {
  color: #7c3aed;
  font-weight: 600;
}

.nac-batch-actions {
  display: flex;
  gap: 6px;
}

.nac-batch-btn {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  border: 1.5px solid;
  cursor: pointer;
  transition: opacity 0.15s;
  font-family: inherit;
}

.nac-batch-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nac-batch-btn--run {
  background: #ecfdf5;
  color: #15803d;
  border-color: rgba(22, 163, 74, 0.3);
}

.nac-batch-btn--run:hover:not(:disabled) {
  background: #d1fae5;
}

.nac-batch-btn--stop {
  background: #fef2f2;
  color: #b91c1c;
  border-color: rgba(185, 28, 28, 0.3);
}

.nac-batch-btn--stop:hover {
  background: #fee2e2;
}

@media (max-width: 768px) {
  .nac-container { height: 100dvh !important; min-height: 0; }
  .nac-sidebar { width: min(86vw, 320px); }
  .nac-toolbar { padding: 10px 12px; gap: 8px; }
  .nac-toolbar-btns { gap: 4px; }
  .nac-tbtn { padding: 6px 8px; font-size: 10px; }
  .nac-tb-status { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nac-chat-area { padding: 14px 10px; }
  .nac-messages { gap: 12px; }
  .nac-bubble { max-width: 94%; }
  .nac-bubble-content { padding: 10px 12px; }
  .nac-input-area { padding: 8px 10px 10px; }
  .nac-suggestions { gap: 5px; }
  .nac-suggest-chip { max-width: 78vw; overflow: hidden; text-overflow: ellipsis; }
}

@media (max-width: 480px) {
  .nac-tb-status { display: none; }
  .nac-toolbar-btns .nac-tbtn { font-size: 0; padding: 7px; }
  .nac-toolbar-btns .nac-tbtn svg { margin: 0; }
  .nac-toolbar-btns .nac-tbtn:first-child::after { content: '+'; font-size: 16px; line-height: 12px; }
  .nac-input-wrap { min-width: 0; }
  .nac-input { font-size: 16px; }
  .nac-form { gap: 6px; }
  .nac-btn-icon { flex: 0 0 38px; width: 38px; height: 38px; }
}

.nac-md-numbered {
  margin: 8px 0 12px 20px;
  padding: 0;
  font-size: 13px;
  line-height: 1.65;
  color: #334155;
}

.nac-md-num-item {
  margin-bottom: 6px;
}

.nac-md-h3 {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  margin: 12px 0 6px;
}

.nac-md-hr {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 14px 0;
}

.nac-snapshot-streaming-cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  background-color: #4f46e5;
  margin-left: 3px;
  vertical-align: middle;
  border-radius: 1px;
  animation: nac-blink-cursor 0.8s infinite;
}

@keyframes nac-blink-cursor {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ═══════════════════════════════════════════════════════════════════════════
   OWZY REPORT CARD THEME (brown + cream) — parity with SFA
   ═══════════════════════════════════════════════════════════════════════════ */
:root {
  --owzy-ink: #1e293b; --owzy-ink-soft: #475569; --owzy-brown: #4f46e5;
  --owzy-brown-dark: #4338ca; --owzy-cream: #ffffff; --owzy-cream-2: #f7f9fc;
  --owzy-sand: #eef1f6; --owzy-border: #e3e9f2; --owzy-muted: #8a94a6;
}
.nac-snapshot-card { display: flex; flex-direction: column; gap: 10px; width: 100%; }
.nab-card { background: var(--owzy-cream); border: 1px solid var(--owzy-border); border-radius: 20px; padding: 22px 24px 18px; color: var(--owzy-ink); font-family: inherit; animation: nab-card-in 0.38s cubic-bezier(0.22,0.85,0.3,1) both; }
@keyframes nab-card-in { from { opacity: 0; transform: translateY(8px) scale(0.995); } to { opacity: 1; transform: none; } }
.nab-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.nab-brand { font-size: 12.5px; font-weight: 800; color: var(--owzy-brown); }
.nab-range-pill { display: inline-flex; align-items: center; gap: 7px; font-size: 11px; font-weight: 650; color: var(--owzy-ink-soft); background: var(--owzy-cream); border: 1px solid var(--owzy-border); padding: 6px 12px; border-radius: 999px; white-space: nowrap; }
.nab-range-arrow { color: var(--owzy-brown); }
.nab-title { font-size: 23px; font-weight: 800; letter-spacing: -0.015em; color: var(--owzy-brown); margin: 2px 0 8px; }
.nab-intro { font-size: 13.5px; color: var(--owzy-ink-soft); line-height: 1.55; margin: 0; }
.nab-intro strong { color: var(--owzy-brown-dark); }
.nab-row2 { display: flex; align-items: stretch; justify-content: space-between; gap: 14px; margin: 14px 0 12px; flex-wrap: wrap; }
.nab-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; flex: 1; min-width: 260px; }
.nab-tile { display: flex; align-items: center; gap: 10px; background: var(--owzy-cream-2); border: 1px solid var(--owzy-border); border-radius: 14px; padding: 12px 14px; }
.nab-tile-ic { width: 34px; height: 34px; flex-shrink: 0; border-radius: 10px; background: var(--owzy-sand); color: var(--owzy-brown); display: flex; align-items: center; justify-content: center; }
.nab-tile-val { font-size: 17px; font-weight: 800; color: var(--owzy-ink); line-height: 1.1; }
.nab-tile-lbl { font-size: 10.5px; color: var(--owzy-muted); font-weight: 600; margin-top: 2px; }
.nab-value-card { display: flex; align-items: center; gap: 12px; background: linear-gradient(135deg, var(--owzy-cream-2), var(--owzy-sand)); border: 1px solid var(--owzy-border); border-radius: 14px; padding: 14px 20px; min-width: 210px; }
.nab-value-icon { color: var(--owzy-brown); }
.nab-value-num { font-size: 26px; font-weight: 800; color: var(--owzy-brown); line-height: 1.05; }
.nab-value-lbl { font-size: 11px; font-weight: 650; color: var(--owzy-muted); }
.nab-meta-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 11.5px; color: var(--owzy-muted); padding: 2px 2px 12px; flex-wrap: wrap; }
.nab-biggest strong { color: var(--owzy-brown-dark); font-weight: 750; }
.nab-avg { color: var(--owzy-muted); font-weight: 600; white-space: nowrap; }
.nab-grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 14px; }
.nab-panel { background: var(--owzy-cream-2); border: 1px solid var(--owzy-border); border-radius: 16px; padding: 16px 18px; min-width: 0; }
.nab-panel-title { font-size: 15.5px; font-weight: 800; color: var(--owzy-brown-dark); margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--owzy-border); }
.nab-leaders-scroll { max-height: 264px; overflow-y: auto; border-radius: 10px; }
.nab-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.nab-table thead th { position: sticky; top: 0; z-index: 2; text-align: left; font-size: 10.5px; font-weight: 700; color: var(--owzy-muted); text-transform: uppercase; letter-spacing: 0.04em; background: var(--owzy-cream-2); padding: 6px 8px; border-bottom: 1px solid var(--owzy-border); }
.nab-table tbody td { padding: 8px; border-bottom: 1px solid rgba(79, 70, 229,0.08); vertical-align: middle; }
.nab-table tbody tr:nth-child(odd) { background: rgba(79, 70, 229,0.035); }
.nab-td-rank { font-weight: 800; color: var(--owzy-brown); width: 26px; }
.nab-td-name strong { font-weight: 750; color: var(--owzy-ink); }
.nab-td-num { text-align: right; font-variant-numeric: tabular-nums; }
.nab-tr-rest td { border-top: 2px solid var(--owzy-border); background: var(--owzy-sand) !important; }
.nab-td-rest { color: var(--owzy-brown); font-weight: 800; }
.nab-td-restname strong { color: var(--owzy-brown-dark); }
.nab-sharecell { display: flex; align-items: center; gap: 7px; min-width: 96px; }
.nab-sharecell i { height: 8px; border-radius: 5px; min-width: 4px; background: linear-gradient(90deg, #4f46e5, #a5b4fc); display: inline-block; }
.nab-sharecell span { font-size: 11px; font-weight: 700; color: var(--owzy-ink-soft); }
.nab-mix { display: flex; align-items: center; gap: 18px; }
.nab-donut-wrap { position: relative; width: 148px; height: 148px; flex-shrink: 0; }
.nab-donut-wrap canvas { width: 148px !important; height: 148px !important; }
.nab-donut-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; color: var(--owzy-ink); pointer-events: none; }
.nab-donut-center span { font-size: 10px; font-weight: 700; color: var(--owzy-muted); }
.nab-legend { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.nab-dot { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
.nab-dot--anchor { background: #4f46e5; } .nab-dot--core { background: #6366f1; } .nab-dot--tail { background: #a5b4fc; } .nab-dot--dormant { background: #e3e9f2; }
.nab-tier { display: flex; gap: 9px; min-width: 0; }
.nab-tier-name { font-size: 11.5px; color: var(--owzy-ink); }
.nab-tier-meta { font-size: 11px; color: var(--owzy-muted); margin-top: 2px; line-height: 1.45; }
.nab-line { display: flex; gap: 11px; padding: 9px 0; border-bottom: 1px dashed var(--owzy-border); }
.nab-line:last-child { border-bottom: none; }
.nab-line-icon { width: 32px; height: 32px; flex-shrink: 0; border-radius: 50%; background: var(--owzy-sand); color: var(--owzy-brown); display: flex; align-items: center; justify-content: center; }
.nab-line-title { font-size: 12px; font-weight: 750; color: var(--owzy-ink); }
.nab-line-text { font-size: 11.5px; color: var(--owzy-ink-soft); line-height: 1.5; margin-top: 2px; }
.nab-panel--explore { margin-bottom: 12px; }
.nab-explore-head { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 800; color: var(--owzy-brown-dark); margin-bottom: 12px; }
.nab-explore { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
@media (max-width: 640px) { .nab-explore { grid-template-columns: 1fr; } }
.nab-chip { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: var(--owzy-cream); border: 1px solid var(--owzy-border); border-radius: 12px; padding: 10px 14px; font-size: 12px; font-weight: 650; color: var(--owzy-ink); cursor: pointer; font-family: inherit; text-align: left; transition: border-color 0.15s, background 0.15s, transform 0.1s; }
.nab-chip:hover { border-color: var(--owzy-brown); background: var(--owzy-cream-2); transform: translateY(-1px); }
.nab-chip-arrow { color: var(--owzy-brown); font-weight: 800; }
.nab-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 10.5px; color: var(--owzy-muted); padding-top: 12px; border-top: 1px solid var(--owzy-border); }
.nab-foot-brand { color: var(--owzy-brown); font-weight: 800; }
.nab-panel--analysis { grid-column: 1 / -1; }
.nab-analysis-body { font-size: 12.5px; line-height: 1.6; color: var(--owzy-ink); animation: nac-fade-up 0.35s ease-out both; }
.nab-analysis-body .nac-md-h1 { color: var(--owzy-brown); border-bottom: 1px solid var(--owzy-border); }
.nab-analysis-body .nac-md-h2 { display: flex; align-items: center; gap: 8px; margin: 12px 0 8px; padding: 9px 11px; border-radius: 11px; color: var(--owzy-brown-dark); background: linear-gradient(90deg, var(--owzy-cream), var(--owzy-cream-2)); border: 1px solid var(--owzy-border); font-weight: 750; }
.nab-analysis-body .nac-md-h3 { color: var(--owzy-ink); }
.nab-analysis-body .nac-md-bullets li { background: var(--owzy-cream); border: 1px solid var(--owzy-border); border-radius: 9px; color: var(--owzy-ink-soft); }
.nab-analysis-loading { display: flex; flex-direction: column; gap: 10px; }
.nab-analysis-loading-text { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 750; color: var(--owzy-brown); }
.nab-analysis-loading-bar { height: 5px; border-radius: 5px; overflow: hidden; background: rgba(79, 70, 229,0.08); }
.nab-analysis-loading-bar i { display: block; height: 100%; width: 45%; border-radius: 5px; background: linear-gradient(90deg, rgba(79, 70, 229,0.15), var(--owzy-brown), rgba(79, 70, 229,0.35)); animation: nab-sweep 1.7s ease-in-out infinite; }
@keyframes nab-sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(240%); } }
.nab-narrating { background: var(--owzy-cream-2); border: 1px solid var(--owzy-border); border-radius: 14px; padding: 12px 16px; }
.nab-narrating-head { display: flex; gap: 11px; align-items: center; }
.nab-narrating-avatar { width: 30px; height: 30px; border-radius: 10px; flex-shrink: 0; background: linear-gradient(135deg, var(--owzy-brown-dark), var(--owzy-brown)); color: #fff; font-weight: 800; font-size: 13px; display: flex; align-items: center; justify-content: center; }
.nab-narrating-title { font-size: 12.5px; font-weight: 800; color: var(--owzy-ink); }
.nab-narrating-steps { display: flex; align-items: center; gap: 7px; margin-top: 3px; flex-wrap: wrap; }
.nab-step { font-size: 10px; font-weight: 700; color: var(--owzy-ink-soft); background: var(--owzy-sand); border-radius: 999px; padding: 3px 9px; white-space: nowrap; }
.nab-step--live { color: var(--owzy-brown); background: var(--owzy-cream); border: 1px solid var(--owzy-border); }
.nab-narrating-sep { color: #a5b4fc; font-size: 10px; }
.nab-narrating-bar { margin-top: 10px; height: 4px; border-radius: 4px; background: rgba(79, 70, 229,0.08); overflow: hidden; }
.nab-narrating-bar i { display: block; height: 100%; width: 45%; border-radius: 4px; background: linear-gradient(90deg, rgba(79, 70, 229,0.15), var(--owzy-brown), rgba(79, 70, 229,0.35)); animation: nab-sweep 1.7s ease-in-out infinite; }
@keyframes nac-fade-up { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.nac-snapshot-streaming-cursor { background-color: var(--owzy-brown); }

/* Multi-Ask example chips */
.nac-batch-examples { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 2px 2px 10px; }
.nac-batch-examples-label { font-size: 11px; font-weight: 700; color: var(--owzy-muted); }
.nac-batch-example { border: 1px solid var(--owzy-border); background: var(--owzy-cream); color: var(--owzy-brown); border-radius: 999px; padding: 4px 11px; font-size: 11px; font-weight: 650; cursor: pointer; font-family: inherit; transition: background 0.15s, border-color 0.15s, transform 0.1s; }
.nac-batch-example:hover:not(:disabled) { background: var(--owzy-sand); border-color: var(--owzy-brown); transform: translateY(-1px); }
.nac-batch-example:disabled { opacity: 0.5; cursor: not-allowed; }

/* Warm up the report table + chart surfaces */
.nac-table-wrap { border: 1px solid var(--owzy-border); border-radius: 12px; background: #fff; }
.nac-table th { background: var(--owzy-cream-2); color: var(--owzy-brown-dark); }
.nac-table td { color: var(--owzy-ink); }
.nac-chart-canvas-wrap { border: 1px solid var(--owzy-border); border-radius: 10px; }
.nab-foot-right { display: inline-flex; align-items: center; gap: 10px; }
.nab-pdf-btn { border: 1px solid var(--owzy-border); background: var(--owzy-cream-2); color: var(--owzy-brown); border-radius: 8px; padding: 5px 12px; font-size: 11px; font-weight: 750; cursor: pointer; font-family: inherit; transition: background 0.15s, border-color 0.15s, transform 0.1s; }
.nab-pdf-btn:hover:not(:disabled) { background: var(--owzy-sand); border-color: var(--owzy-brown); transform: translateY(-1px); }
.nab-pdf-btn:disabled { opacity: 0.6; cursor: not-allowed; }

/* Message action bar (copy / like / dislike / report / PDF) */
.nac-turn { display: flex; flex-direction: column; }
.nac-msg-actions { display: flex; align-items: center; gap: 4px; margin: -4px 0 10px 46px; padding: 3px; width: max-content; border-radius: 12px; background: var(--owzy-sand); }
.nac-ma-btn { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; padding: 0; border: none; border-radius: 8px; background: transparent; color: var(--owzy-muted); cursor: pointer; transition: background 0.15s, color 0.15s, transform 0.1s; }
.nac-ma-btn:hover { background: var(--owzy-cream-2); color: var(--owzy-brown); }
.nac-ma-btn:active { transform: scale(0.9); }
.nac-ma-btn--active { color: var(--owzy-brown); background: rgba(79, 70, 229,0.14); }
.nac-ma-pdf-wrap { position: relative; display: inline-flex; }
.nac-report-menu { position: absolute; bottom: calc(100% + 6px); left: 0; z-index: 60; min-width: 240px; padding: 8px; border-radius: 12px; background: #fff; border: 1px solid var(--owzy-border); box-shadow: 0 12px 30px rgba(30, 41, 59,0.18); }
.nac-report-head { display: flex; align-items: center; justify-content: space-between; font-size: 12px; font-weight: 750; color: var(--owzy-brown-dark); padding: 2px 4px 8px; border-bottom: 1px solid var(--owzy-border); }
.nac-report-close { border: none; background: transparent; font-size: 18px; color: var(--owzy-muted); cursor: pointer; line-height: 1; padding: 0 4px; border-radius: 6px; }
.nac-report-close:hover { color: var(--owzy-brown); background: var(--owzy-sand); }
.nac-report-options { display: flex; flex-direction: column; gap: 2px; padding-top: 6px; }
.nac-report-options button { text-align: left; border: 1px solid transparent; background: transparent; color: var(--owzy-ink-soft); font-size: 11.5px; padding: 6px 8px; border-radius: 8px; cursor: pointer; font-family: inherit; }
.nac-report-options button:hover { background: var(--owzy-cream-2); border-color: var(--owzy-border); }
.nac-report-done { font-size: 11.5px; color: #248a4b; padding: 6px 8px; }
.nac-ma-spinner { width: 13px; height: 13px; border-radius: 50%; border: 2px solid rgba(79, 70, 229,0.25); border-top-color: var(--owzy-brown); animation: nac-spin 0.7s linear infinite; }
@keyframes nac-spin { to { transform: rotate(360deg); } }
.nac-btn--export { background: var(--owzy-cream-2); border: 1px solid var(--owzy-border); color: var(--owzy-brown); }
.nac-btn--export:hover { background: var(--owzy-sand); border-color: var(--owzy-brown); }
.nac-btn--report { background: linear-gradient(145deg, var(--owzy-brown), #4338ca); border: 1px solid var(--owzy-brown); color: #fff; }
.nac-btn--report:hover { background: var(--owzy-brown-dark); border-color: var(--owzy-brown-dark); }

/* ═══════════════════════════════════════════════════════════════════════════
   OWZY CHAT THEME — full UI re-skin (parity with SFA native chat)
   ═══════════════════════════════════════════════════════════════════════════ */
.nac-container { background: var(--owzy-cream); color: var(--owzy-ink); }
.nac-main { background: var(--owzy-cream); }
.nac-chat-area {
  background:
    radial-gradient(circle at 88% 10%, rgba(129, 140, 248, 0.10), transparent 26%),
    linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
}
.nac-chat-area::-webkit-scrollbar-thumb { background: #c7d0de; }

/* Toolbar */
.nac-toolbar { background: rgba(255, 250, 243, 0.96); border-bottom-color: rgba(79, 70, 229, 0.13); box-shadow: 0 5px 18px rgba(30, 41, 59, 0.045); }
.nac-tb-title { color: var(--owzy-ink); }
.nac-tb-status { color: var(--owzy-muted); }
.nac-tb-avatar { background: linear-gradient(145deg, #eef1f6, #a5b4fc); border: 1px solid rgba(79, 70, 229, 0.14); box-shadow: 0 5px 14px rgba(79, 70, 229, 0.12); }
.nac-tbtn { background: #f7f9fc; border-color: rgba(79, 70, 229, 0.16); color: var(--owzy-brown); }
.nac-tbtn:hover { background: #eef2f8; border-color: rgba(79, 70, 229, 0.42); }
.nac-tbtn--active, .nac-tbtn--active:hover { background: var(--owzy-brown); border-color: var(--owzy-brown); color: #fff; }

/* Sidebar */
.nac-sidebar { background: #ffffff; border-right-color: var(--owzy-border); }
.nac-sidebar-title { color: var(--owzy-ink); }
.nac-sidebar-item { background: #ffffff; border-color: var(--owzy-border); }
.nac-sidebar-item:hover { border-color: #a5b4fc; box-shadow: 0 3px 10px rgba(79, 70, 229, 0.07); }
.nac-sidebar-item-q { color: var(--owzy-ink); }
.nac-sidebar-new-btn { background: var(--owzy-brown); }
.nac-sidebar-new-btn:hover { background: var(--owzy-brown-dark); }
.nac-sidebar-icon-btn:hover, .nac-sidebar-toggle:hover { background: var(--owzy-sand); }
.nac-sidebar-act-btn:hover { background: #eef2f8; color: var(--owzy-brown); }
.nac-sidebar-rename-input { border-color: var(--owzy-orange); }
.nac-logo { background: linear-gradient(135deg, var(--owzy-brown), #6d5cf6); color: #fff; }

/* Avatars + bubbles — assistant avatar is the Owzy mascot */
.nac-msg-avatar--assistant {
  background: url('/d3/owzy-mascot.png') center / contain no-repeat,
              linear-gradient(145deg, #fff2d4, #ffc56f);
  box-shadow: 0 4px 12px rgba(139, 47, 16, 0.16);
  border: 1px solid rgba(194, 65, 12, 0.12);
}
.nac-msg-avatar--assistant > svg { display: none; }
.nac-msg-avatar--user { background: linear-gradient(145deg, #64748b, #334155); box-shadow: 0 3px 10px rgba(51, 65, 85, 0.28); }
.nac-bubble-content--assistant { background: rgba(255, 255, 255, 0.9); border-color: var(--owzy-border); box-shadow: 0 7px 22px rgba(30, 41, 59, 0.055); }
.nac-bubble-content--user { background: linear-gradient(135deg, #f7f9fc, #eef1f6); border-color: #e3e9f2; color: var(--owzy-ink); }
.nac-bubble-title--assistant { color: var(--owzy-brown); }
.nac-bubble-title--user { color: var(--owzy-brown-dark); }
.nac-bubble-body { color: #334155; }

/* Markdown */
.nac-md-content { color: #334155; }
.nac-md-content strong { color: var(--owzy-brown-dark); }
.nac-md-h1 { color: var(--owzy-brown); border-bottom-color: var(--owzy-border); }
.nac-md-h2 { color: var(--owzy-brown-dark); background: linear-gradient(90deg, #f7f9fc, #fff8ed); border: 1px solid #dcdafc; border-radius: 11px; padding: 9px 11px; }
.nac-md-h3 { color: var(--owzy-ink); }
.nac-md-bullets li { background: #fffaf4; border: 1px solid #eef2f8; border-radius: 9px; color: var(--owzy-ink-soft); }
.nac-md-bullets li::before { content: "\\2022"; color: var(--owzy-orange); }
.nac-md-code { background: #f7f9fc; border-color: #dcdafc; color: var(--owzy-brown-dark); }
.nac-md-tbl-wrap { border-color: var(--owzy-border); }
.nac-md-table thead tr { background: linear-gradient(135deg, var(--owzy-brown), #4338ca); }
.nac-md-table thead th { color: #fff; }
.nac-md-table tbody tr:nth-child(even) { background: #ffffff; }
.nac-md-table tbody tr:hover { background: var(--owzy-cream-2); }
.nac-md-num-item { border-color: #dcdafc; background: linear-gradient(90deg, #f7f9fc, #ffffff); color: #334155; }
.nac-md-num-item::before { color: var(--owzy-brown-dark); background: #a5b4fc; }
.nac-md-hr { border-top-color: var(--owzy-border); }

/* Thinking */
.nac-thinking-header, .nac-thinking-step-text { color: var(--owzy-brown); }
.nac-thinking-pulse { background: var(--owzy-orange); box-shadow: 0 0 0 0 rgba(109, 92, 246, 0.48); }
.nac-thinking-bar-wrap { background: #eef2f8; }
.nac-thinking-bar-fill { background: linear-gradient(90deg, var(--owzy-brown), var(--owzy-orange), var(--owzy-gold)); }

/* Multi-result cards */
.nac-multi-card { border-color: var(--owzy-border); background: var(--owzy-cream); }
.nac-multi-card-title { color: var(--owzy-ink); }

/* Composer */
.nac-input-area { background: rgba(255, 252, 247, 0.98); border-top-color: var(--owzy-border); }
.nac-input-wrap { border-color: #e2e8f0; background: #fff; box-shadow: 0 3px 14px rgba(30, 41, 59, 0.04); }
.nac-input-wrap:focus-within { border-color: var(--owzy-orange); box-shadow: 0 0 0 3px rgba(109, 92, 246, 0.1); }
.nac-input { color: var(--owzy-ink); }
.nac-input::placeholder { color: #94a3b8; }
.nac-suggest-chip { background: #f7f9fc; border-color: rgba(79, 70, 229, 0.14); color: var(--owzy-brown); }
.nac-suggest-chip:hover { background: #dcdafc; border-color: var(--owzy-orange); color: var(--owzy-brown-dark); }
.nac-btn-send { background: linear-gradient(145deg, var(--owzy-brown), #4338ca); }
.nac-btn-voice { background: linear-gradient(145deg, #6d5cf6, var(--owzy-orange) 52%, #6d5cf6); }
.nac-btn-voice::before { background: linear-gradient(135deg, #818cf8, #8b5cf6, #4f46e5); }

/* Voice overlay */
.nac-voice-label, .nac-voice-sublabel { color: var(--owzy-brown-dark); }
.nac-voice-back { color: var(--owzy-ink-soft); }

/* Hidden-table notice */
.nac-table-hidden-notice { background: #e6e5fb; border-color: rgba(109, 92, 246, 0.34); color: var(--owzy-brown); }

/* ═══════════════════════════════════════════════════════════════════════════
   CLEAN INDIGO THEME — colors only (overrides everything above)
   ═══════════════════════════════════════════════════════════════════════════ */
.nac-container { --accent: #4f46e5; --accent-soft: #e6e5fb; --ink: #1e293b; --ink-2: #64748b; --muted: #8a94a6; --page: #eef1f6; --line: #e3e9f2; }
.nac-container, .nac-main, .nac-chat-area { background: var(--page); color: var(--ink); }
.nac-chat-area::-webkit-scrollbar-thumb { background: #c7d0de; }

.nac-bubble-content--assistant,
.nac-bubble-content--user { background: #ffffff; border-color: #e8edf4; box-shadow: 0 2px 10px rgba(30, 41, 59, 0.06); color: var(--ink); }
.nac-bubble-title--assistant, .nac-bubble-title--user { color: var(--muted); }
.nac-bubble-body { color: var(--ink); }

.nac-toolbar { background: #ffffff; border-bottom-color: #e8edf4; box-shadow: 0 2px 10px rgba(30, 41, 59, 0.05); }
.nac-tb-title { color: var(--ink); }
.nac-tb-status { color: var(--muted); }
.nac-tb-avatar { background: var(--accent); border: none; color: #fff; }
.nac-tbtn { background: #fff; border-color: #e3e9f2; color: var(--accent); }
.nac-tbtn:hover { background: var(--accent-soft); border-color: var(--accent); }
.nac-tbtn--active, .nac-tbtn--active:hover { background: var(--accent); border-color: var(--accent); color: #fff; }
.nac-sidebar { background: #f7f9fc; border-right-color: #e8edf4; }
.nac-sidebar-title { color: var(--ink); }
.nac-sidebar-item { background: #fff; border-color: #e8edf4; }
.nac-sidebar-item:hover { border-color: var(--accent); box-shadow: 0 2px 10px rgba(79, 70, 229, 0.08); }
.nac-sidebar-item-q { color: var(--ink); }
.nac-sidebar-new-btn { background: var(--accent); }
.nac-sidebar-new-btn:hover { background: #4338ca; }
.nac-sidebar-icon-btn:hover, .nac-sidebar-toggle:hover, .nac-sidebar-act-btn:hover { background: var(--accent-soft); color: var(--accent); }
.nac-logo { background: var(--accent); color: #fff; }

.nac-bubble-body, .nac-md-content { color: var(--ink); }
.nac-md-content strong { color: var(--ink); }
.nac-md-h1 { color: var(--accent); border-bottom-color: #e8edf4; }
.nac-md-h2 { color: var(--accent); background: var(--accent-soft); border-color: #dcdafc; }
.nac-md-h3 { color: var(--ink); }
.nac-md-bullets li { background: #fff; border-color: #e8edf4; color: var(--ink-2); }
.nac-md-bullets li::before { color: var(--accent); }
.nac-md-num-item { background: #fff; border-color: #e8edf4; color: var(--ink-2); }
.nac-md-num-item::before { color: #fff; background: var(--accent); }
.nac-md-code { background: var(--accent-soft); border-color: #dcdafc; color: var(--accent); }
.nac-md-tbl-wrap { border-color: #e8edf4; }
.nac-md-table thead tr, .nac-md-table thead th { background: var(--accent); color: #fff; }
.nac-md-table tbody tr:nth-child(even) { background: #f7f9fc; }
.nac-md-table tbody tr:hover { background: var(--accent-soft); }
.nac-md-hr { border-top-color: #e8edf4; }

.nac-table th { background: var(--accent-soft); color: var(--accent); }
.nac-table td { color: var(--ink-2); border-top-color: #eef2f8; }
.nac-table tr:hover td { background: var(--accent-soft); }
.nac-table-wrap, .nac-multi-card { border-color: #e8edf4; }
.nac-multi-card { background: #fff; }
.nac-multi-card-title { color: var(--ink); }
.nac-chart-container { background: #fff; border-color: #e8edf4; }
.nac-ct-btn, .nac-chart-select { background: #fff; border-color: #dfe4ee; color: var(--ink-2); }
.nac-ct-btn:hover, .nac-chart-select:hover { background: var(--accent-soft); border-color: var(--accent); }
.nac-ct-btn--active { background: var(--accent); border-color: var(--accent); color: #fff; }
.nac-table-hidden-notice { background: var(--accent-soft); border-color: rgba(79, 70, 229, 0.35); color: var(--accent); }

.nac-input-area { background: #f7f9fc; border-top-color: #e8edf4; }
.nac-input-wrap { border-color: #dfe4ee; background: #fff; box-shadow: 0 2px 10px rgba(30, 41, 59, 0.05); }
.nac-input-wrap:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12); }
.nac-input { color: var(--ink); }
.nac-input::placeholder { color: #9aa4b2; }
.nac-suggest-chip { background: var(--accent-soft); border-color: transparent; color: var(--accent); }
.nac-suggest-chip:hover { background: #dcdafc; border-color: var(--accent); color: var(--accent); }
.nac-btn-send, .nac-btn-voice { background: var(--accent); }
.nac-btn-voice::before { background: linear-gradient(135deg, #7c6cf8, #4f46e5); }

.nac-thinking-header, .nac-thinking-step-text { color: var(--accent); }
.nac-thinking-pulse { background: var(--accent); box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.5); }
.nac-thinking-bar-wrap { background: #e8edf4; }
.nac-thinking-bar-fill { background: linear-gradient(90deg, #6a5af9, var(--accent), #8b5cf6); }

.nac-msg-actions { background: #eef1f6; }
.nac-ma-btn { color: var(--muted); }
.nac-ma-btn:hover { background: var(--accent-soft); color: var(--accent); }
.nac-ma-btn--active { color: var(--accent); background: var(--accent-soft); }
.nac-ma-cta--ghost { background: #fff; border-color: #dfe4ee; color: var(--accent); }
.nac-ma-cta--ghost:hover:not(:disabled) { background: var(--accent-soft); border-color: var(--accent); }
.nac-ma-cta--solid { background: var(--accent); border-color: var(--accent); color: #fff; box-shadow: 0 3px 10px rgba(79, 70, 229, 0.22); }
.nac-ma-cta--solid:hover { background: #4338ca; }
.nac-ma-spinner { border-color: rgba(79, 70, 229, 0.25); border-top-color: var(--accent); }
.nab-pdf-btn { background: #fff; border-color: #dfe4ee; color: var(--accent); }
.nab-pdf-btn:hover:not(:disabled) { background: var(--accent-soft); border-color: var(--accent); }

.nac-modal { background: #fff; border-color: #e8edf4; }
.nac-modal-input:focus { border-color: var(--accent); }
.nac-modal-btn--confirm { background: var(--accent); border-color: var(--accent); }
.nac-report-submit { background: var(--accent); border-color: var(--accent); }

.nac-snapshot-streaming-cursor { background-color: var(--accent); }

/* ── Zero-data friendly empty state ─────────────────────────────────────── */
.nac-nodata-card {
  display: flex; flex-direction: column; align-items: center; text-align: center;
  gap: 6px; padding: 18px 16px; background: #ffffff;
  border: 1px solid #e8edf4; border-radius: 14px;
  box-shadow: 0 2px 10px rgba(30, 41, 59, 0.05);
}
.nac-nodata-icon {
  width: 40px; height: 40px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--accent-soft, #e6e5fb); color: var(--accent, #4f46e5);
}
.nac-nodata-title { font-size: 13.5px; font-weight: 600; color: #1e293b; }
.nac-nodata-sub { font-size: 12px; color: #64748b; max-width: 420px; line-height: 1.5; }
.nac-nodata-chips { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-top: 6px; }
.nac-nodata-chips .nac-suggest-chip { font-size: 11.5px; padding: 6px 10px; border-radius: 999px; cursor: pointer; }
`;

function injectCSSOnce() {
  if (document.getElementById('nac-chat-component-css')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'nac-chat-component-css';
  styleEl.textContent = INJECTED_CSS;
  document.head.appendChild(styleEl);
}

const SUGGESTIONS = [
  'Sales this month',
  'Compare primary and sales performance',
  'Show purchase trends for last 6 months',
  'What is my sales growth vs last month?',
  'Top 5 items by sales this quarter',
  'Which dealers did I sell to most this month?'
];

/* ═══════════════════════════════════════════════════════════════════
   MAIN EXPORTED REACT COMPONENT
   ═══════════════════════════════════════════════════════════════════ */
export default function DMSAIChat({ isMaximized, user }) {
  // DMS AI backend base URL (override via user.dmsAiBaseUrl if needed).
  // Toggle between environments by commenting/uncommenting the desired URL below.
  // const DMS_AI_BASE_URL = 'https://chatbot.eazydms.com'; // Production (Live)
  const DMS_AI_BASE_URL = 'https://chatbotuatnew.eazydms.com'; // UAT (Testing)
  const API_BASE = String(user?.dmsAiBaseUrl || DMS_AI_BASE_URL).replace(/\/$/, '');

  // Identity is passed as request headers.
  const xUid = user?.['X-UID'] || '';
  const uUid = user?.['U-UID'] || '';
  const xBypassUid = user?.['x-bypass-uid'] || '';
  const xAiAnalytics = user?.['x-ai-analytics'] || false;

  // fetchJson — prepends API_BASE, attaches identity headers, adds timeout + retry/abort wrapper.
  const fetchJson = async (url, opts = {}) => {
    const o = { ...opts };
    const headers = { 'Content-Type': 'application/json', ...(o.headers || {}) };
    if (xUid) headers['X-UID'] = xUid;
    if (uUid) headers['U-UID'] = uUid;
    if (xBypassUid) headers['x-bypass-uid'] = xBypassUid;
    headers['x-ai-analytics'] = xAiAnalytics ? 'true' : 'false';
    o.headers = headers;

    const isWriteRequest = (o.method || 'GET').toUpperCase() !== 'GET';
    const timeoutMs = isWriteRequest ? 120000 : 30000;
    const maxRetries = isWriteRequest ? 2 : 1;

    let lastError = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const r = await fetch(API_BASE + url, { ...o, signal: controller.signal });
        clearTimeout(tid);
        let data = null;
        try { data = await r.json(); } catch (_) {}
        return { ok: r.ok, status: r.status, data };
      } catch (err) {
        clearTimeout(tid);
        lastError = err;
        if (err.name === 'AbortError') {
          throw new Error(`Request timed out after ${timeoutMs / 1000}s. Please try again.`);
        }
        if (attempt < maxRetries) {
          await new Promise((res) => setTimeout(res, 500 * (attempt + 1)));
          continue;
        }
      }
    }
    throw new Error(lastError?.message || 'Network request failed. Please check your connection.');
  };

  const fetchServerSessions = async (query = '') => {
    if (!uUid) return null;
    const params = new URLSearchParams({ search: query.trim(), limit: '40' });
    const result = await fetchJson(`/api/chat/history?${params.toString()}`);
    if (!result.ok) throw new Error(result.data?.detail || `History request failed (${result.status})`);
    return Array.isArray(result.data?.sessions) ? result.data.sessions : [];
  };

  // Staff Selection States
  const [staffList, setStaffList] = useState([]);
  const [staffUid, setStaffUid] = useState(() => {
    const fromUser = String(user?.userid || user?.assigned_user_id || user?.['U-UID'] || '');
    return fromUser || localStorage.getItem('dms_analytics_uid') || '';
  });
  const [staffLoading, setStaffLoading] = useState(false);

  // Chat/Messages State
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      html: '<p><strong>Owzy</strong> is active. You can request queries or summaries regarding your <strong>secondary sales</strong>, <strong>purchases</strong>, or <strong>primary sales</strong> metrics.</p>'
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);

  // Chat Session States
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [historyQuery, setHistoryQuery] = useState('');
  const conversationContext = useRef([]);
  const lastExecutionData = useRef(null);

  const filteredSessions = useMemo(() => {
    const query = historyQuery.trim().toLocaleLowerCase();
    if (!query) return sessions;
    return sessions.filter(session => {
      const title = String(session.title || '');
      const questions = (session.messages || [])
        .filter(message => message.role === 'user')
        .map(message => message.content || message.text || '')
        .join(' ');
      return `${title} ${questions}`.toLocaleLowerCase().includes(query);
    });
  }, [historyQuery, sessions]);

  // Drawer & Panels
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Voice recognition language preference
  const [langPrefModal, setLangPrefModal] = useState(false);
  const [langModalTab, setLangModalTab] = useState("input"); // "input" (voice) | "output" (AI answers)
  const [selectedLang, setSelectedLang] = useState("ta-IN");

  // Output language preference — language Owzy replies in
  const [outputLang, setOutputLang] = useState("auto");
  const [outputScript, setOutputScript] = useState(() => {
    try {
      return localStorage.getItem(`dms_output_script_${uUid || staffUid}`) || "native";
    } catch (_) { return "native"; }
  });
  const [outputLangOptions, setOutputLangOptions] = useState([
    { code: "auto",  label: "Auto (match question)" },
    { code: "en-IN", label: "English" },
    { code: "hi-IN", label: "Hindi" },
    { code: "ta-IN", label: "Tamil" },
    { code: "te-IN", label: "Telugu" },
    { code: "kn-IN", label: "Kannada" },
    { code: "ml-IN", label: "Malayalam" },
    { code: "mr-IN", label: "Marathi" },
    { code: "gu-IN", label: "Gujarati" },
    { code: "pa-IN", label: "Punjabi" },
    { code: "bn-IN", label: "Bengali" },
    { code: "ur-IN", label: "Urdu" },
  ]);

  // Batch mode (run multiple questions sequentially)
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchText, setBatchText] = useState("");
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchProg, setBatchProg] = useState("");
  const batchStopRef = useRef(false);

  // Modal (AI Excel Report)
  const [modalConfig, setModalConfig] = useState(null);
  const [aiError, setAiError] = useState('');
  const [aiLoading, setAiLoading] = useState(false);

  // Inline renaming
  const [renamingId, setRenamingId] = useState(null);
  const [renameText, setRenameText] = useState('');

  // Voice recording — browser-native SpeechRecognition when available (same
  // engine Own AI's dictation uses), falling back to raw PCM capture +
  // silence detection + server-side transcription otherwise.
  const [voiceMode, setVoiceMode] = useState(false);       // instant UI toggle (full-screen overlay)
  const [recording, setRecording] = useState(false);       // mic is actually capturing
  const [voiceProcessing, setVoiceProcessing] = useState(false);

  const voiceStreamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const inputNodeRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const silenceStartRef = useRef(null);
  const hasSpokenRef = useRef(false);
  const pcmBuffers = useRef([]);
  const pcmLength = useRef(0);
  const recordingRef = useRef(false);

  // Browser SpeechRecognition (Web Speech API) — feature-detected upgrade path
  // for non-WebView contexts. Noticeably more accurate than raw-audio →
  // backend STT for most languages/devices, and avoids the backend entirely.
  const recognitionRef = useRef(null);
  const webSpeechFinalRef = useRef("");
  const webSpeechSilenceTimerRef = useRef(null);
  const voiceCancelledRef = useRef(false);

  const SILENCE_THRESHOLD = 0.015;   // RMS below this = silence
  const SILENCE_DURATION = 2000;     // ms of silence before auto-stop
  const MIN_SPEECH_DURATION = 500;   // ms of speech required before silence detection kicks in

  // Text-to-speech — reads an assistant bubble aloud via the browser's built-in
  // Web Speech API (client-side only, no server TTS endpoint involved).
  const [speakingMsgId, setSpeakingMsgId] = useState(null); // id of the message currently being spoken, or null
  const speechSupported = typeof window !== "undefined" && !!window.speechSynthesis;

  const cleanForSpeech = useCallback((html) => {
    if (!html) return "";
    return String(html)
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<\/(td|th)>/gi, ", ")
      .replace(/<\/(tr|li|p|div|h[1-6])>/gi, ". ")
      .replace(/<br\s*\/?>/gi, ". ")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&bull;/gi, "-")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/^\s*\|.*\|\s*$/gm, "")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/\s+/g, " ")
      .trim();
  }, []);

  const speakMessage = useCallback((html, id) => {
    if (!speechSupported) return;
    // Toggle off: clicking the currently-speaking message's button stops it.
    if (speakingMsgId === id) {
      window.speechSynthesis.cancel();
      setSpeakingMsgId(null);
      return;
    }
    // Stop any other utterance in progress before starting a new one.
    window.speechSynthesis.cancel();
    const text = cleanForSpeech(html);
    if (!text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = () => setSpeakingMsgId(prev => (prev === id ? null : prev));
    utterance.onerror = () => setSpeakingMsgId(prev => (prev === id ? null : prev));
    setSpeakingMsgId(id);
    window.speechSynthesis.speak(utterance);
  }, [speechSupported, speakingMsgId, cleanForSpeech]);

  // Chart library check
  const [chartReady, setChartReady] = useState(!!window.Chart);

  // DOM Refs
  const chatRef = useRef(null);

  // ── Initialization ──────────────────────────────────────────
  useEffect(() => {
    injectCSSOnce();
  }, []);

  useEffect(() => {
    if (window.Chart) {
      setChartReady(true);
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
    script.onload = () => setChartReady(true);
    document.head.appendChild(script);
  }, []);

  // Restore the saved voice-recognition language preference for this user
  useEffect(() => {
    const stored = localStorage.getItem(`dms_lang_pref_${uUid || staffUid}`);
    if (stored) setSelectedLang(stored);
  }, [uUid, staffUid]);

  // Restore/refresh the AI output-language preference for this user
  useEffect(() => {
    loadOutputLang();
  }, [uUid, staffUid]);

  // Update sessions when selected staff member changes
  useEffect(() => {
    if (!staffUid) return undefined;
    localStorage.setItem('dms_analytics_uid', staffUid);
    let cancelled = false;
    const initializeSessions = async () => {
      let list = loadSessions(staffUid);
      try {
        const serverList = await fetchServerSessions();
        if (serverList) list = serverList;
      } catch (error) {
        console.warn('[DMSAIChat] Server history unavailable; using local history fallback.', error);
      }
      if (cancelled) return;
      setSessions(list);

      // Resume only today's latest session. Older sessions remain searchable history.
      const today = getLocalDateKey();
      const todaysSession = list
        .filter(session => getSessionDateKey(session) === today)
        .sort((a, b) => new Date(b.updated || b.created).getTime() - new Date(a.updated || a.created).getTime())[0];
      if (todaysSession) loadSession(todaysSession);
      else startNewConversation(staffUid);
    };
    initializeSessions();
    return () => { cancelled = true; };
  }, [staffUid, uUid]);

  useEffect(() => {
    if (!uUid || !staffUid) return undefined;
    const timer = setTimeout(async () => {
      try {
        const serverList = await fetchServerSessions(historyQuery);
        if (serverList) setSessions(serverList);
      } catch (error) {
        console.warn('[DMSAIChat] History search failed; retaining current results.', error);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [historyQuery, staffUid, uUid]);

  // Keep messages scrolled to bottom
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages, loading]);

  // ── Selected User helpers ────────────────────────────────────
  const getSelectedStaff = () => {
    return staffList.find(s => s.userid === staffUid) || null;
  };

  const getSelectedStaffName = () => {
    const s = getSelectedStaff();
    return s ? (s.name || s.username) : staffUid;
  };

  // ── Voice Transcription — raw PCM capture, silence auto-stop, server STT ──
  const pushSystemMessage = (html) => {
    setMessages(prev => [...prev, { id: 'sys-' + Date.now(), role: 'assistant', html }]);
  };

  function startSilenceDetection() {
    const analyser = audioCtxRef.current.createAnalyser();
    analyser.fftSize = 2048;
    analyserRef.current = analyser;
    inputNodeRef.current.connect(analyser);

    const dataArray = new Float32Array(analyser.fftSize);
    silenceStartRef.current = null;
    hasSpokenRef.current = false;
    const recordStartTime = Date.now();

    silenceTimerRef.current = setInterval(() => {
      if (!recordingRef.current) { clearInterval(silenceTimerRef.current); return; }

      analyser.getFloatTimeDomainData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i];
      const rms = Math.sqrt(sum / dataArray.length);

      if (rms > SILENCE_THRESHOLD) {
        // Speech detected
        hasSpokenRef.current = true;
        silenceStartRef.current = null;
      } else if (hasSpokenRef.current && (Date.now() - recordStartTime) > MIN_SPEECH_DURATION) {
        // Silence after speech
        if (!silenceStartRef.current) {
          silenceStartRef.current = Date.now();
        } else if (Date.now() - silenceStartRef.current >= SILENCE_DURATION) {
          // Silence long enough — auto-stop
          stopVoice();
        }
      }
    }, 100);
  }

  function cleanupSilenceDetection() {
    if (silenceTimerRef.current) { clearInterval(silenceTimerRef.current); silenceTimerRef.current = null; }
    try { analyserRef.current?.disconnect(); } catch (_) {}
    analyserRef.current = null;
    silenceStartRef.current = null;
    hasSpokenRef.current = false;
  }

  // Detect React Native WebView
  const isInReactNativeWebView = () => !!window.ReactNativeWebView;

  // Listen for voice results from React Native
  useEffect(() => {
    const handler = (event) => {
      try {
        const msg = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
        if (msg?.type === "voice-result") {
          setRecording(false);
          recordingRef.current = false;
          setVoiceProcessing(false);
          setVoiceMode(false);
          if (msg.transcript) {
            sendChatMessage(msg.transcript);
          } else {
            pushSystemMessage(`<p>${escHtml(msg.error || "No speech detected. Please try again.")}</p>`);
          }
        } else if (msg?.type === "voice-recording") {
          setRecording(true);
          recordingRef.current = true;
        } else if (msg?.type === "voice-stopped") {
          setRecording(false);
          recordingRef.current = false;
          setVoiceProcessing(true);
        }
      } catch (_) {}
    };
    window.addEventListener("message", handler);
    document.addEventListener("message", handler); // Android WebView fires on document
    return () => {
      window.removeEventListener("message", handler);
      document.removeEventListener("message", handler);
    };
  }, []);

  // Cleanup silence detection + any in-progress speech synthesis on unmount
  useEffect(() => {
    return () => {
      cleanupSilenceDetection();
      if (recognitionRef.current) { try { recognitionRef.current.abort(); } catch (_) {} }
      if (webSpeechSilenceTimerRef.current) clearTimeout(webSpeechSilenceTimerRef.current);
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    };
  }, []);

  async function startVoice() {
    if (recordingRef.current || voiceMode) return;

    // In React Native WebView — delegate voice to native app via bridge
    if (isInReactNativeWebView()) {
      setVoiceMode(true);
      window.ReactNativeWebView.postMessage(JSON.stringify({ type: "voice-start" }));
      return;
    }

    // Prefer the browser's native SpeechRecognition when available — same
    // engine Own AI's dictation uses, and noticeably more accurate than the
    // raw-audio → backend STT fallback below for most languages/devices.
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      startVoiceWebSpeech(SR);
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      pushSystemMessage(`<p>${escHtml("Microphone not supported in this browser.")}</p>`);
      return;
    }

    // Show voice mode overlay INSTANTLY before any async work
    setVoiceMode(true);

    try {
      // 1. Create AudioContext FIRST (must happen in user-gesture callback on mobile)
      audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtxRef.current.state === "suspended") {
        await audioCtxRef.current.resume();
      }

      // 2. Request mic — try with constraints, fall back to bare { audio: true }
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (_) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
      voiceStreamRef.current = stream;

      // 3. Create source node — wrap in try to handle sampleRate mismatches
      try {
        inputNodeRef.current = audioCtxRef.current.createMediaStreamSource(stream);
      } catch (srcErr) {
        await audioCtxRef.current.close();
        const track = stream.getAudioTracks()[0];
        const settings = track.getSettings?.() || {};
        audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: settings.sampleRate || 44100,
        });
        if (audioCtxRef.current.state === "suspended") {
          await audioCtxRef.current.resume();
        }
        inputNodeRef.current = audioCtxRef.current.createMediaStreamSource(stream);
      }

      pcmBuffers.current = [];
      pcmLength.current = 0;

      // 4. Try AudioWorklet first, fall back to ScriptProcessor
      try {
        const workletScript = `
          let pcmBuffer = [];
          class PCMProcessor extends AudioWorkletProcessor {
            process(inputs) {
              const input = inputs[0];
              if (input.length > 0) {
                const chunk = input[0];
                for (let i = 0; i < chunk.length; i++) pcmBuffer.push(chunk[i]);
                if (pcmBuffer.length > 8192) {
                  this.port.postMessage({ pcmData: pcmBuffer });
                  pcmBuffer = [];
                }
              }
              return true;
            }
          }
          registerProcessor('pcm-processor', PCMProcessor);
        `;
        const blob = new Blob([workletScript], { type: "application/javascript" });
        const url = URL.createObjectURL(blob);
        await audioCtxRef.current.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        const workletNode = new AudioWorkletNode(audioCtxRef.current, "pcm-processor");
        workletNode.port.onmessage = e => {
          if (!recordingRef.current) return;
          const floatData = new Float32Array(e.data.pcmData);
          pcmBuffers.current.push(floatData);
          pcmLength.current += floatData.length;
        };
        processorRef.current = workletNode;
      } catch (_) {
        const scriptNode = audioCtxRef.current.createScriptProcessor(4096, 1, 1);
        scriptNode.onaudioprocess = e => {
          if (!recordingRef.current) return;
          const chunk = new Float32Array(e.inputBuffer.getChannelData(0));
          pcmBuffers.current.push(chunk);
          pcmLength.current += chunk.length;
        };
        processorRef.current = scriptNode;
      }

      inputNodeRef.current.connect(processorRef.current);
      processorRef.current.connect(audioCtxRef.current.destination);
      recordingRef.current = true;
      setRecording(true);

      // Start monitoring for silence to auto-stop
      startSilenceDetection();
    } catch (e) {
      setVoiceMode(false);
      setRecording(false);
      recordingRef.current = false;
      try { voiceStreamRef.current?.getTracks().forEach(t => t.stop()); } catch (_) {}
      try { audioCtxRef.current?.close(); } catch (_) {}
      pushSystemMessage(`<p>${escHtml(e?.message || "Failed to start recording")}</p>`);
    }
  }

  // Browser SpeechRecognition path — same auto-submit-on-silence UX as the
  // raw-audio fallback, just backed by the browser's own (Google/Apple) STT
  // engine instead of our custom /api/speech/transcribe endpoint.
  function startVoiceWebSpeech(SR) {
    setVoiceMode(true);
    try {
      const rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = selectedLang || "en-IN";
      rec.maxAlternatives = 1;
      webSpeechFinalRef.current = "";
      voiceCancelledRef.current = false;
      recognitionRef.current = rec;

      rec.onstart = () => {
        recordingRef.current = true;
        setRecording(true);
      };

      rec.onresult = (ev) => {
        let final = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const r = ev.results[i];
          if (r.isFinal) final += r[0].transcript;
        }
        if (final) webSpeechFinalRef.current += (webSpeechFinalRef.current ? " " : "") + final.trim();
        // Reset silence timer — auto-stop after a pause, same UX as the raw-audio path
        if (webSpeechSilenceTimerRef.current) clearTimeout(webSpeechSilenceTimerRef.current);
        webSpeechSilenceTimerRef.current = setTimeout(() => { try { rec.stop(); } catch (_) {} }, SILENCE_DURATION);
      };

      rec.onerror = (e) => {
        if (e?.error === "no-speech" || e?.error === "aborted") return; // benign — onend will still fire
        recordingRef.current = false;
        setRecording(false);
        setVoiceMode(false);
        setVoiceProcessing(false);
        recognitionRef.current = null;
        pushSystemMessage(`<p>${escHtml("Microphone error: " + (e?.error || "unknown"))}</p>`);
      };

      rec.onend = () => {
        recordingRef.current = false;
        setRecording(false);
        if (webSpeechSilenceTimerRef.current) { clearTimeout(webSpeechSilenceTimerRef.current); webSpeechSilenceTimerRef.current = null; }
        recognitionRef.current = null;
        if (voiceCancelledRef.current) { voiceCancelledRef.current = false; setVoiceMode(false); setVoiceProcessing(false); return; }
        const text = webSpeechFinalRef.current.trim();
        setVoiceMode(false);
        setVoiceProcessing(false);
        if (text) {
          sendChatMessage(text);
        } else {
          pushSystemMessage(`<p>${escHtml("No speech detected. Please try again.")}</p>`);
        }
      };

      rec.start();
    } catch (e) {
      setVoiceMode(false);
      setRecording(false);
      recordingRef.current = false;
      recognitionRef.current = null;
      pushSystemMessage(`<p>${escHtml(e?.message || "Failed to start recording")}</p>`);
    }
  }

  function exitVoiceMode() {
    // Tell RN to cancel voice if in WebView
    if (isInReactNativeWebView()) {
      try { window.ReactNativeWebView.postMessage(JSON.stringify({ type: "voice-cancel" })); } catch (_) {}
    }
    // Browser SpeechRecognition path — abort without submitting whatever was heard
    if (recognitionRef.current) {
      voiceCancelledRef.current = true;
      try { recognitionRef.current.abort(); } catch (_) {}
      recognitionRef.current = null;
    }
    if (webSpeechSilenceTimerRef.current) { clearTimeout(webSpeechSilenceTimerRef.current); webSpeechSilenceTimerRef.current = null; }
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
    setVoiceMode(false);
    setRecording(false);
    setVoiceProcessing(false);
    recordingRef.current = false;
    cleanupSilenceDetection();
    try {
      processorRef.current?.disconnect();
      inputNodeRef.current?.disconnect();
      voiceStreamRef.current?.getTracks().forEach(t => t.stop());
      audioCtxRef.current?.close();
    } catch (_) {}
  }

  async function stopVoice() {
    // RN WebView path — tell native to stop
    if (isInReactNativeWebView()) {
      setRecording(false);
      recordingRef.current = false;
      setVoiceProcessing(true);
      window.ReactNativeWebView.postMessage(JSON.stringify({ type: "voice-stop" }));
      return;
    }
    // Browser SpeechRecognition path — stop() triggers a final onresult + onend,
    // which handles submitting the transcript itself.
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch (_) {}
      return;
    }
    if (!recordingRef.current) return;
    recordingRef.current = false;
    setRecording(false);
    cleanupSilenceDetection();
    try {
      processorRef.current?.disconnect();
      inputNodeRef.current?.disconnect();
      voiceStreamRef.current?.getTracks().forEach(t => t.stop());
    } catch (_) {}

    if (pcmLength.current === 0) {
      setVoiceMode(false);
      pushSystemMessage(`<p>${escHtml("No audio was captured. Please check your microphone.")}</p>`);
      return;
    }

    // Combine float PCM buffers
    const combinedPcm = new Float32Array(pcmLength.current);
    let off = 0;
    for (const chunk of pcmBuffers.current) { combinedPcm.set(chunk, off); off += chunk.length; }

    // Resample from source rate to 16kHz
    const srcRate = audioCtxRef.current ? audioCtxRef.current.sampleRate : 48000;
    const resampledPcm = resampleAudio(combinedPcm, srcRate, 16000);

    // Convert to 16-bit PCM and encode as WAV
    const pcm16 = floatTo16BitPCM(resampledPcm);

    try {
      await audioCtxRef.current?.close();
    } catch (_) {}

    try {
      setVoiceProcessing(true);
      const wavBuffer = encodeWav(pcm16, 16000);
      const bytes = new Uint8Array(wavBuffer);
      let binary = "";
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
      const resp = await fetchJson("/api/speech/transcribe", {
        method: "POST",
        body: JSON.stringify({ audio_b64: btoa(binary), sample_rate_hz: 16000, sample_width: 2, lang: selectedLang }),
      });
      if (!resp.ok) {
        setVoiceMode(false);
        setVoiceProcessing(false);
        pushSystemMessage(`<p>${escHtml(resp.data?.detail || "Transcription failed")}</p>`);
        return;
      }
      const text = resp.data?.transcript ? String(resp.data.transcript) : "";
      // Exit voice mode, then auto-submit
      setVoiceMode(false);
      setVoiceProcessing(false);
      if (text) {
        sendChatMessage(text);
      } else {
        pushSystemMessage(`<p>${escHtml("No speech detected. Please try again.")}</p>`);
      }
    } catch (e) {
      setVoiceMode(false);
      setVoiceProcessing(false);
      pushSystemMessage(`<p>${escHtml(e?.message || "Failed to transcribe")}</p>`);
    }
  }

  // ── Chat Actions & APIs ──────────────────────────────────────
  const sendChatMessage = async (messageText) => {
    if (!messageText.trim()) return;
    setInputText('');

    // Add user message
    setMessages(prev => [...prev, { id: 'u-' + Date.now(), role: 'user', text: messageText }]);

    // Add assistant placeholder bubble
    const loadingId = 'ai-loading-' + Date.now();
    setMessages(prev => [...prev, { id: loadingId, role: 'assistant', loadingPlaceholder: true }]);
    setLoading(true);

    try {
      // Phase 1: Request data execution + flag selection
      const resp = await fetchJson('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          userid: uUid || staffUid,
          message: messageText,
          session_id: currentSessionId,
          history: conversationContext.current.slice(-10),
          name: user?.firstName,
          email: user?.email,
          phase: 1
        })
      });

      const data = resp.data || {};

      if (data.session_id) setCurrentSessionId(data.session_id);

      if (!resp.ok) {
        const serverMsg = data.error || data.message || data.detail || `Server error (${resp.status})`;
        throw new Error(serverMsg);
      }

      // Extract data query details for Excel export
      let sourceRows = data.rows || [];
      let sourceCols = data.columns || [];
      if (sourceRows.length > 0) {
        lastExecutionData.current = { columns: sourceCols, rows: sourceRows };
      }

      const chartSpec = (data.chart_spec && data.chart_spec.chart_type) ? data.chart_spec : null;
      const chartRows = chartSpec ? (chartSpec.rows || sourceRows) : [];
      const chartCols = chartSpec ? (chartSpec.columns || sourceCols) : [];

      // Check if this was resolved directly in Phase 1 (e.g. conversational/general greeting) or legacy single-phase response
      const isDirectPhase1 = data.phase === null || !data.job_token || !!data.answer;

      if (isDirectPhase1) {
        const answer = data.answer || 'No response could be parsed.';
        setMessages(prev => prev.map(m => m.id === loadingId ? {
          id: 'ai-' + Date.now(),
          role: 'assistant',
          html: renderMarkdown(answer),
          chartSpec,
          chartRows,
          chartCols,
          hasData: sourceRows.length > 0,
          noData: sourceRows.length === 0 && !!data.flag,
          briefing: data.briefing || null,
          suggestions: Array.isArray(data.suggestions) ? data.suggestions : []
        } : m));

        conversationContext.current = [
          ...conversationContext.current,
          { role: 'user', content: messageText },
          {
            role: 'assistant',
            content: answer,
            chartSpec: chartSpec || undefined,
            chartRows: chartRows.slice(0, 50),
            chartCols: chartCols,
            hasData: sourceRows.length > 0
          }
        ].slice(-20);

        let activeSid = data.session_id || currentSessionId;
        const activeSession = activeSid
          ? loadSessions(staffUid).find(session => session.id === activeSid)
          : null;
        if (!data.session_id && (!activeSession || getSessionDateKey(activeSession) !== getLocalDateKey())) {
          activeSid = createNewSession(staffUid);
          setCurrentSessionId(activeSid);
        }
      // Snapshot for history replay (SFA parity): cols/rows/chart/briefing.
      const turnSnapshot = {
        cols: (chartCols && chartCols.length ? chartCols : sourceCols) || [],
        rows: (chartRows && chartRows.length ? chartRows : sourceRows).slice(0, 100),
        chartSpec: chartSpec || null,
        briefing: data.briefing || null,
        answer: answer,
      };
      autoSaveSession(staffUid, activeSid, conversationContext.current, turnSnapshot);
        try {
          const serverList = await fetchServerSessions();
          setSessions(serverList || loadSessions(staffUid));
        } catch (_) {
          setSessions(loadSessions(staffUid));
        }
        return;
      }

      // ── Phase 2: Progressive Streaming via OCI Generative AI ──────────
      // First show the Phase 1 Data Snapshot & Chart immediately with a live streaming indicator
      const activeMsgId = 'ai-' + Date.now();
      let streamAnswer = '';
      let streamBriefing = data.briefing || null;
      let streamSuggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
      setMessages(prev => prev.map(m => m.id === loadingId ? {
        id: activeMsgId,
        role: 'assistant',
        html: renderMarkdown('Analyzing operational field data...', true),
        chartSpec,
        chartRows,
        chartCols,
        hasData: sourceRows.length > 0,
        noData: sourceRows.length === 0 && !!data.flag,
        briefing: streamBriefing,
        suggestions: streamSuggestions,
        streaming: true,
      } : m));

      // Stream tokens from Phase 2
      try {
        const streamHeaders = {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        };
        if (xUid) streamHeaders['X-UID'] = xUid;
        if (uUid) streamHeaders['U-UID'] = uUid;
        if (xBypassUid) streamHeaders['x-bypass-uid'] = xBypassUid;
        streamHeaders['x-ai-analytics'] = 'true';

        const p2Resp = await fetch(API_BASE + '/api/chat', {
          method: 'POST',
          headers: streamHeaders,
          body: JSON.stringify({
            userid: uUid || staffUid,
            phase: 2,
            job_token: data.job_token,
            stream: true,
          }),
        });

        const cType = p2Resp.headers.get('content-type') || '';
        if (p2Resp.ok && p2Resp.body && (cType.includes('text/event-stream') || cType.includes('octet-stream'))) {
          const reader = p2Resp.body.getReader();
          const decoder = new TextDecoder();
          let buf = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop() || '';

            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed.startsWith('data:')) continue;
              const jsonStr = trimmed.slice(5).trim();
              if (!jsonStr) continue;
              try {
                const parsed = JSON.parse(jsonStr);
                if (parsed.briefing) streamBriefing = parsed.briefing;
                if (Array.isArray(parsed.suggestions) && parsed.suggestions.length) {
                  streamSuggestions = parsed.suggestions;
                }
                if (parsed.full_answer) {
                  streamAnswer = parsed.full_answer;
                } else if (parsed.delta) {
                  streamAnswer += parsed.delta;
                }
                const isFinal = parsed.done;
                setMessages(prev => prev.map(m => m.id === activeMsgId ? {
                  ...m,
                  html: renderMarkdown(streamAnswer || 'Synthesizing briefing...', !isFinal),
                  streaming: !isFinal,
                  briefing: streamBriefing,
                  suggestions: streamSuggestions,
                } : m));
              } catch (_) {}
            }
          }
        } else {
          // Non-streaming fallback for Phase 2
          const p2Json = await p2Resp.json().catch(() => ({}));
          streamAnswer = p2Json.answer || p2Json.detail || 'Analysis complete.';
          if (p2Json.briefing) streamBriefing = p2Json.briefing;
          if (Array.isArray(p2Json.suggestions) && p2Json.suggestions.length) streamSuggestions = p2Json.suggestions;
        }
      } catch (p2Err) {
        console.warn('[DMSAIChat] Phase 2 stream error:', p2Err);
        if (!streamAnswer) streamAnswer = 'Data snapshot generated successfully.';
      }

      // Stream complete: finalize message and remove cursor
      const finalAns = streamAnswer || 'Analysis complete.';
      setMessages(prev => prev.map(m => m.id === activeMsgId ? {
        ...m,
        html: renderMarkdown(finalAns, false),
        streaming: false,
        briefing: streamBriefing,
        suggestions: streamSuggestions,
      } : m));

      conversationContext.current = [
        ...conversationContext.current,
        { role: 'user', content: messageText },
        {
          role: 'assistant',
          content: finalAns,
          chartSpec: chartSpec || undefined,
          chartRows: chartRows.slice(0, 50),
          chartCols: chartCols,
          hasData: sourceRows.length > 0
        }
      ].slice(-20);

      let activeSid = data.session_id || currentSessionId;
      const activeSession = activeSid
        ? loadSessions(staffUid).find(session => session.id === activeSid)
        : null;
      if (!data.session_id && (!activeSession || getSessionDateKey(activeSession) !== getLocalDateKey())) {
        activeSid = createNewSession(staffUid);
        setCurrentSessionId(activeSid);
      }
      autoSaveSession(staffUid, activeSid, conversationContext.current);
      try {
        const serverList = await fetchServerSessions();
        setSessions(serverList || loadSessions(staffUid));
      } catch (_) {
        setSessions(loadSessions(staffUid));
      }

    } catch (e) {
      console.error('[DMSAIChat] Chat request failed:', e);
      setMessages(prev => prev.map(m => m.id === loadingId ? {
        id: 'err-' + Date.now(),
        role: 'assistant',
        html: `<div class="dms-modal-error">⚠️ ${escHtml(friendlyErrorMessage(e, 'We could not process that request. Please try again.'))}</div>`
      } : m));
    } finally {
      setLoading(false);
    }
  };

  // ── Batch mode (run multiple questions sequentially) ──────────
  async function runBatch() {
    const lines = batchText.split("\n").map(l => l.trim()).filter(Boolean);
    if (!lines.length) {
      setBatchProg("Enter at least one question (one per line).");
      return;
    }
    batchStopRef.current = false;
    setBatchRunning(true);
    for (let i = 0; i < lines.length; i++) {
      if (batchStopRef.current) break;
      setBatchProg(`Running ${i + 1}/${lines.length}: ${lines[i].slice(0, 40)}...`);
      if (i > 0) pushSystemMessage(`<p>── Question ${i + 1} of ${lines.length} ──</p>`);
      await sendChatMessage(lines[i]);
      await new Promise(r => setTimeout(r, 400));
    }
    setBatchRunning(false);
    setBatchProg(batchStopRef.current ? "Stopped." : `Done — ran ${lines.length} questions.`);
  }

  // ── Security helpers ─────────────────────────────────────────

  /** Validate BCP-47 language code — prevents any injection via the select value. */
  function _isValidLangCode(code) {
    return typeof code === "string" && /^(?:auto|[a-z]{2,3}-[A-Z]{2,4})$/.test(code);
  }

  // ── Output Language ───────────────────────────────────────────

  async function loadOutputLang() {
    const uid = uUid || staffUid;
    if (!uid) return;
    // 1. Instant paint from localStorage cache — avoids layout shift
    try {
      const cached = localStorage.getItem(`dms_output_lang_${uid}`);
      if (cached && _isValidLangCode(cached)) setOutputLang(cached);
    } catch (_) {}
    // 2. Fetch live options + saved preference from backend in parallel
    try {
      const [optRes, langRes] = await Promise.all([
        fetchJson(`/api/prefs/options/output-lang`),
        fetchJson(`/api/prefs/output-lang?uid=${encodeURIComponent(uid)}`),
      ]);
      if (optRes.ok && Array.isArray(optRes.data?.available_langs) && optRes.data.available_langs.length > 0) {
        setOutputLangOptions(optRes.data.available_langs);
      }
      if (langRes.ok && langRes.data?.lang && _isValidLangCode(langRes.data.lang)) {
        setOutputLang(langRes.data.lang);
        try { localStorage.setItem(`dms_output_lang_${uid}`, langRes.data.lang); } catch (_) {}
      }
    } catch (_) { /* offline — stay with localStorage cache */ }
  }

  async function loadOutputScript() {
    const uid = uUid || staffUid;
    if (!uid) return;
    try {
      const resp = await fetchJson(`/api/prefs/output-script?uid=${encodeURIComponent(uid)}`);
      if (resp.ok && resp.data?.script) {
        setOutputScript(resp.data.script);
        try { localStorage.setItem(`dms_output_script_${uid}`, resp.data.script); } catch (_) {}
      }
    } catch (_) {}
  }

  async function saveOutputScript(scriptVal) {
    if (scriptVal !== "native" && scriptVal !== "roman") return;
    setOutputScript(scriptVal);
    const uid = uUid || staffUid;
    try { if (uid) localStorage.setItem(`dms_output_script_${uid}`, scriptVal); } catch (_) {}
    if (!uid) return;
    try {
      await fetchJson(`/api/prefs/output-script`, {
        method: "POST",
        body: JSON.stringify({ uid, script: scriptVal }),
      });
    } catch (_) {}
  }

  async function saveOutputLang(lang) {
    if (!_isValidLangCode(lang)) return; // security: reject any non-BCP-47 value
    setOutputLang(lang);                  // optimistic UI update
    const uid = uUid || staffUid;
    try { if (uid) localStorage.setItem(`dms_output_lang_${uid}`, lang); } catch (_) {}
    if (!uid) return;
    try {
      await fetchJson(`/api/prefs/output-lang`, {
        method: "POST",
        body: JSON.stringify({ uid, lang }),
      });
    } catch (_) { /* best-effort — UI already updated optimistically */ }
  }

  // ── Conversation Lifecycle ───────────────────────────────────
  const startNewConversation = (uidVal = staffUid) => {
    if (!uidVal) return;
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        html: '<p>👋 Welcome back to <strong>Owzy</strong>. Ask me anything about your <strong>secondary sales</strong>, <strong>purchases</strong>, or <strong>primary sales</strong> metrics.</p>'
      }
    ]);
    conversationContext.current = [];
    setCurrentSessionId(null);
    setHistoryQuery('');
    lastExecutionData.current = null;
    setSidebarOpen(false);
  };

const loadSession = (session) => {
if (!session || !session.messages) return;
const rebuiltMessages = [];
session.messages.forEach((m, index) => {
if (m.role === 'user') {
rebuiltMessages.push({ id: 'rebuilt-' + index, role: 'user', text: m.content });
} else {
// SFA parity: rebuild the unified report card when the turn carries a
// data snapshot (briefing/chart/table), like loadConversation in SFA.
const snap = m.data_snapshot || (index === session.messages.length - 1 ? session.data_snapshot : null);
const _snap = snap && (snap.cols?.length || snap.rows?.length || snap.chartSpec || snap.briefing) ? snap : null;
if (_snap) {
rebuiltMessages.push({
id: 'rebuilt-' + index,
role: 'assistant',
html: renderMarkdown(m.content),
briefing: _snap.briefing || null,
chartSpec: _snap.chartSpec || null,
chartRows: _snap.rows || [],
chartCols: _snap.cols || [],
hasData: (_snap.rows?.length || 0) > 0
});
} else {
rebuiltMessages.push({
id: 'rebuilt-' + index,
role: 'assistant',
html: renderMarkdown(m.content),
chartSpec: m.chartSpec || null,
chartRows: m.chartRows || [],
chartCols: m.chartCols || [],
hasData: !!m.hasData || (m.chartRows && m.chartRows.length > 0)
});
}
}
});

setMessages(rebuiltMessages.length > 0 ? rebuiltMessages : [
{
id: 'welcome',
role: 'assistant',
html: '<p>👋 Welcome back. Let\'s continue our conversation.</p>'
}
]);
conversationContext.current = session.messages.map(m => ({ role: m.role, content: m.content }));
setCurrentSessionId(session.id);
// Restore the last execution data so Export / AI Excel work after replay.
const lastSnap = (() => {
for (let i = session.messages.length - 1; i >= 0; i--) {
const s = session.messages[i].data_snapshot || (i === session.messages.length - 1 ? session.data_snapshot : null);
if (s && (s.rows?.length || s.cols?.length)) return s;
}
return null;
})();
lastExecutionData.current = lastSnap ? { columns: lastSnap.cols || [], rows: lastSnap.rows || [] } : null;
setSidebarOpen(false);
};

  const handleDeleteSession = (sid) => {
    setModalConfig({
      title: 'Delete Conversation',
      message: 'Are you sure you want to delete this chat session?',
      onConfirm: () => {
        setModalConfig(null);
        const updated = deleteSession(staffUid, sid);
        setSessions(updated);
        if (currentSessionId === sid) {
          startNewConversation();
        }
      },
    });
  };

  const triggerRenameSession = (sid, currentTitle) => {
    setRenamingId(sid);
    setRenameText(currentTitle);
  };

  const saveRenamedSession = (sid) => {
    if (renameText.trim()) {
      const updated = renameSession(staffUid, sid, renameText.trim());
      setSessions(updated);
    }
    setRenamingId(null);
  };

  // ── Excel and PDF Exporting ──────────────────────────────────
  const downloadBlob = async (path, payload, defaultFilename) => {
    const headers = { 'Content-Type': 'application/json' };
    if (xUid) headers['X-UID'] = xUid;
    if (uUid) headers['U-UID'] = uUid;
    if (xBypassUid) headers['x-bypass-uid'] = xBypassUid;
    headers['x-ai-analytics'] = xAiAnalytics ? 'true' : 'false';
    const res = await fetch(API_BASE + path, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || 'Failed to generate spreadsheet file');
    }

    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = payload.filename || defaultFilename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  };

  const handleStandardExport = async () => {
    const data = lastExecutionData.current;
    if (!data || !data.rows.length) {
      alert('No tabular data available to export. Run a natural language data query first.');
      return;
    }
    try {
      await downloadBlob('/api/export/xlsx', {
        columns: data.columns,
        rows: data.rows,
        filename: 'dms_data_export_' + Date.now() + '.xlsx'
      }, 'export.xlsx');
    } catch (e) {
      console.error('[DMSAIChat] Standard export failed:', e);
      alert(friendlyErrorMessage(e, 'We could not export the data. Please try again.'));
    }
  };

  const handleSmartAIExport = async (smartPrompt) => {
    const data = lastExecutionData.current;
    if (!data || !data.rows.length) return;

    setAiError('');
    setAiLoading(true);
    try {
      await downloadBlob('/api/export/smart', {
        prompt: smartPrompt,
        columns: data.columns,
        rows: data.rows,
        filename: 'dms_smart_report_' + Date.now() + '.xlsx'
      }, 'report.xlsx');
      setModalConfig(null);
    } catch (e) {
      console.error('[DMSAIChat] Smart export failed:', e);
      setAiError(friendlyErrorMessage(e, 'We could not generate the report. Please try again.'));
    } finally {
      setAiLoading(false);
    }
  };

  const handlePrintToPDF = () => {
    if (messages.length <= 1) {
      alert('Start a conversation and fetch some data before printing a PDF.');
      return;
    }
    const metadata = document.createElement('div');
    metadata.style.cssText = 'font-size:10px; color:#64748b; margin-top:20px; padding-top:10px; border-top:1px dashed #334155;';
    metadata.textContent = `Owzy Report — Generated: ${new Date().toLocaleString('en-IN')} | User ID: ${getSelectedStaffName()}`;
    chatRef.current?.appendChild(metadata);
    window.print();
    setTimeout(() => metadata.remove(), 600);
  };

  // ── Handlers ─────────────────────────────────────────────────
  const handleKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage(inputText);
    }
  };

  // ── Render ───────────────────────────────────────────────────
  return (
    <div className="nac-container" style={{ height: isMaximized ? "calc(100vh - 50px)" : "72vh" }}>
      {/* AI Excel Report / Confirm Modal */}
      {modalConfig && (
        <NacModal
          title={modalConfig.title}
          message={modalConfig.message}
          showInput={modalConfig.showInput}
          inputPlaceholder={modalConfig.inputPlaceholder}
          showReportChips={modalConfig.showReportChips}
          onConfirm={modalConfig.onConfirm}
          onCancel={() => setModalConfig(null)}
        />
      )}
      {aiError && (
        <div className="nac-modal-overlay" onClick={() => setAiError('')}>
          <div className="nac-modal" onClick={e => e.stopPropagation()} style={{ width: 380 }}>
            <div className="nac-modal-title">AI Excel Report</div>
            <div className="nac-modal-message" style={{ color: '#dc2626' }}>⚠️ {aiError}</div>
            <div className="nac-modal-actions">
              <button className="nac-modal-btn nac-modal-btn--confirm" onClick={() => setAiError('')}>OK</button>
            </div>
          </div>
        </div>
      )}

      {/* Language Preference Modal — voice input language + AI output language, as tabs */}
      {langPrefModal && (
        <div className="nac-modal-overlay" onClick={() => setLangPrefModal(false)}>
          <div className="nac-modal" onClick={e => e.stopPropagation()} style={{ width: 380 }}>
            <div className="nac-modal-title">🌐 Language Settings</div>
            <div className="nac-lpm-tabs">
              <button
                type="button"
                className={`nac-lpm-tab${langModalTab === "input" ? " nac-lpm-tab--active" : ""}`}
                onClick={() => setLangModalTab("input")}
              >
                🎤 Input (Voice)
              </button>
              <button
                type="button"
                className={`nac-lpm-tab${langModalTab === "output" ? " nac-lpm-tab--active" : ""}`}
                onClick={() => setLangModalTab("output")}
              >
                💬 Output (Answers)
              </button>
            </div>

            {langModalTab === "input" ? (
              <>
                <div className="nac-modal-message">Select your regional language for better voice recognition accuracy.</div>
                <div className="nac-lpm-grid">
                  {[
                    { lang: "ta-IN", label: "Tamil", flag: "🇮🇳" },
                    { lang: "hi-IN", label: "Hindi", flag: "🇮🇳" },
                    { lang: "te-IN", label: "Telugu", flag: "🇮🇳" },
                    { lang: "kn-IN", label: "Kannada", flag: "🇮🇳" },
                    { lang: "mr-IN", label: "Marathi", flag: "🇮🇳" },
                    { lang: "ml-IN", label: "Malayalam", flag: "🇮🇳" },
                    { lang: "gu-IN", label: "Gujarati", flag: "🇮🇳" },
                    { lang: "en-IN", label: "English", flag: "🇮🇳" },
                  ].map(({ lang, label, flag }) => (
                    <button
                      key={lang}
                      className={`nac-lpm-chip${selectedLang === lang ? " nac-lpm-chip--active" : ""}`}
                      onClick={() => setSelectedLang(lang)}
                    >
                      <span>{flag} {label}</span>
                    </button>
                  ))}
                </div>
                <div className="nac-modal-actions">
                  <button className="nac-modal-btn nac-modal-btn--cancel" onClick={() => setLangPrefModal(false)}>Cancel</button>
                  <button className="nac-modal-btn nac-modal-btn--confirm" onClick={async () => {
                    try {
                      await fetch(API_BASE + "/api/speech/lang-pref", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ uid: uUid || staffUid, third_lang: selectedLang }),
                      });
                    } catch (_) {}
                    localStorage.setItem(`dms_lang_pref_${uUid || staffUid}`, selectedLang);
                    setLangPrefModal(false);
                  }}>Save</button>
                </div>
              </>
            ) : (
              <>
                <div className="nac-modal-message">Choose the language Owzy should reply in.</div>
                <div className="nac-lpm-grid">
                  {outputLangOptions.map(o => (
                    <button
                      key={o.code}
                      type="button"
                      title={o.label}
                      className={`nac-lpm-chip${outputLang === o.code ? " nac-lpm-chip--active" : ""}`}
                      onClick={() => saveOutputLang(o.code)}
                    >
                      <span>{o.code === "auto" ? "Auto" : o.label}</span>
                    </button>
                  ))}
                </div>
                <div className="nac-modal-message" style={{ marginTop: 14 }}>Script / Alphabet:</div>
                <div className="nac-lpm-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <button
                    type="button"
                    className={`nac-lpm-chip${outputScript === "native" ? " nac-lpm-chip--active" : ""}`}
                    onClick={() => saveOutputScript("native")}
                  >
                    <span>{outputScript === "native" ? "✓ " : ""}Native Script</span>
                  </button>
                  <button
                    type="button"
                    className={`nac-lpm-chip${outputScript === "roman" ? " nac-lpm-chip--active" : ""}`}
                    onClick={() => saveOutputScript("roman")}
                  >
                    <span>{outputScript === "roman" ? "✓ " : ""}Roman (English Letters)</span>
                  </button>
                </div>
                <div className="nac-modal-actions">
                  <button className="nac-modal-btn nac-modal-btn--confirm" onClick={() => setLangPrefModal(false)}>Done</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Sidebar Overlay */}
      {sidebarOpen && <div className="nac-sidebar-overlay" onClick={() => setSidebarOpen(false)} />}

      {/* Sidebar — Chat History */}
      <div className={`nac-sidebar ${sidebarOpen ? "nac-sidebar--open" : ""}`}>
        <div className="nac-sidebar-header">
          <div className="nac-sidebar-title">Chat History</div>
          <div className="nac-sidebar-actions">
            <button className="nac-sidebar-icon-btn" onClick={() => { setSessions(loadSessions(staffUid)); }} title="Refresh">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
            <button className="nac-sidebar-icon-btn" onClick={() => setSidebarOpen(false)} title="Close">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
        <div className="nac-history-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" />
          </svg>
          <input
            type="search"
            value={historyQuery}
            onChange={e => setHistoryQuery(e.target.value)}
            placeholder="Search questions..."
            aria-label="Search chat history"
          />
          {historyQuery && (
            <button type="button" className="nac-history-search-clear" onClick={() => setHistoryQuery('')} aria-label="Clear history search">&times;</button>
          )}
        </div>
        <button className="nac-sidebar-clear" onClick={() => setModalConfig({
          title: 'Clear All History',
          message: 'Clear all chat history? This cannot be undone.',
          onConfirm: () => {
            setModalConfig(null);
            try { localStorage.removeItem(getSessKey(staffUid)); setSessions([]); } catch (_) {}
          },
        })}>Clear All</button>
        <div className="nac-sidebar-list">
          {sessions.length === 0 ? (
            <div className="nac-sidebar-empty">No conversations yet</div>
          ) : filteredSessions.length === 0 ? (
            <div className="nac-sidebar-empty">No questions match your search</div>
          ) : (
            filteredSessions.map(s => (
              <div key={s.id} className="nac-sidebar-item" onClick={() => renamingId !== s.id && loadSession(s)}>
                {renamingId === s.id ? (
                  <input
                    className="nac-sidebar-rename-input"
                    value={renameText}
                    autoFocus
                    onClick={e => e.stopPropagation()}
                    onChange={e => setRenameText(e.target.value)}
                    onBlur={() => { saveRenamedSession(s.id); }}
                    onKeyDown={e => {
                      if (e.key === 'Enter') saveRenamedSession(s.id);
                      if (e.key === 'Escape') setRenamingId(null);
                    }}
                  />
                ) : (
                  <div className="nac-sidebar-item-q">{s.title}</div>
                )}
                <div className="nac-sidebar-item-date">{formatTimeAgo(s.updated)}</div>
                <div className="nac-sidebar-item-actions">
                  <button className="nac-sidebar-act-btn" title="Rename" onClick={e => { e.stopPropagation(); setRenamingId(s.id); setRenameText(s.title || ''); }}>
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button className="nac-sidebar-act-btn nac-sidebar-act-del" title="Delete" onClick={e => { e.stopPropagation(); handleDeleteSession(s.id); }}>
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
        <div className="nac-sidebar-footer">
          <button className="nac-sidebar-new-btn" onClick={() => startNewConversation()}>+ New Chat</button>
        </div>
      </div>

      {/* Main area */}
      <div className="nac-main">
        {/* Toolbar */}
        <div className="nac-toolbar">
          <div className="nac-toolbar-info">
            <div>
              <div className="nac-tb-title" style={{ fontWeight: 700, letterSpacing: "-0.01em" }}>Owzy</div>
              <div className="nac-tb-status">
                <span className="nac-status-dot nac-status-dot--green" />
                Online - Get your business insights now
              </div>
            </div>
          </div>
          <div className="nac-toolbar-btns">
            <button
              className="nac-tbtn"
              onClick={() => setLangPrefModal(true)}
              title="Voice input & AI answer language settings"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="2" y1="12" x2="22" y2="12"/>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
              </svg>
              Language
            </button>
            <button
              className={`nac-tbtn${batchOpen ? " nac-tbtn--active" : ""}`}
              onClick={() => setBatchOpen(v => !v)}
              title="Multi-ask — ask several questions at once"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="8" y1="6" x2="21" y2="6" />
                <line x1="8" y1="12" x2="21" y2="12" />
                <line x1="8" y1="18" x2="21" y2="18" />
                <line x1="3" y1="6" x2="3.01" y2="6" />
                <line x1="3" y1="12" x2="3.01" y2="12" />
                <line x1="3" y1="18" x2="3.01" y2="18" />
              </svg>
              Multi
            </button>
            <button
              className={`nac-tbtn${sidebarOpen ? " nac-tbtn--active" : ""}`}
              onClick={() => setSidebarOpen(!sidebarOpen)}
              title="Chat history"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"/>
                <polyline points="12 6 12 12 16 14"/>
              </svg>
              History
            </button>
          </div>
        </div>

        {/* Multi-Ask panel — ask several questions in one go */}
        {batchOpen && (
          <div className="nac-batch-panel">
            <div className="nac-batch-header">
              <span className="nac-batch-title">Multi-Ask</span>
              <span className="nac-batch-hint">Ask several questions at once — Owzy answers them one by one</span>
              <button className="nac-batch-close" onClick={() => !batchRunning && setBatchOpen(false)}>×</button>
            </div>
            <div className="nac-batch-examples">
              <span className="nac-batch-examples-label">Try:</span>
              {['Top items this month', 'Purchases trend 6 months', 'Top 5 distributors', 'Closing stock by zone'].map(ex => (
                <button
                  key={ex}
                  type="button"
                  className="nac-batch-example"
                  disabled={batchRunning}
                  onClick={() => setBatchText(t => (t.trim() ? t.replace(/\s*$/, '') + '\n' : '') + ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
            <textarea
              className="nac-batch-textarea"
              rows={4}
              value={batchText}
              onChange={e => setBatchText(e.target.value)}
              placeholder={"How many orders this week?\nShow purchases for April\nTop 5 outlets by secondary sales"}
            />
            <div className="nac-batch-footer">
              <span className={`nac-batch-prog${batchRunning ? " nac-batch-prog--running" : ""}`}>{batchProg}</span>
              <div className="nac-batch-actions">
                {batchRunning && (
                  <button className="nac-batch-btn nac-batch-btn--stop" onClick={() => { batchStopRef.current = true; }}>
                    ■ Stop
                  </button>
                )}
                <button className="nac-batch-btn nac-batch-btn--run" onClick={runBatch} disabled={batchRunning}>
                  ▶ Run all
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Chat */}
        <div className="nac-chat-area" ref={chatRef}>
          <div className="nac-messages">
            {messages.map((m, mi) => {
              if (m.role === 'user') {
                return (
                  <ChatBubble key={m.id} role="user" title="You" body={m.text} />
                );
              }
              if (m.loadingPlaceholder) {
                return (
                  <div className="nac-bubble nac-bubble--assistant" key={m.id}>
                    <div className="nac-msg-avatar nac-msg-avatar--assistant nac-msg-avatar--thinking" title="Owzy">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z"/>
                      </svg>
                    </div>
                    <div className="nac-bubble-content nac-bubble-content--assistant">
                      <ThinkingState />
                    </div>
                  </div>
                );
              }
              const hasChart = m.chartSpec && m.chartRows && m.chartRows.length > 0;
              const hasBriefing = !!(m.briefing && m.briefing.tiles);
              const hasSuggestions = Array.isArray(m.suggestions) && m.suggestions.length > 0;
              const tableCols = hasChart && m.chartCols && m.chartCols.length ? m.chartCols : (m.hasData ? (lastExecutionData.current?.columns || []) : []);
              const tableRows = hasChart ? m.chartRows : (m.hasData ? (lastExecutionData.current?.rows || []) : []);
              const useCard = hasBriefing || hasChart || (!!m.noData && hasSuggestions);
              const onAiReport = () => {
                if (!lastExecutionData.current?.columns?.length) return;
                setModalConfig({
                  title: "AI Excel Report",
                  message: "Describe the report you want, or pick a template:",
                  showInput: true,
                  showReportChips: true,
                  inputPlaceholder: "e.g. Summary with charts and highlights",
                  onConfirm: async (promptText) => {
                    if (!promptText) return;
                    await handleSmartAIExport(promptText);
                  },
                });
              };
              const _q = (() => {
                for (let k = mi - 1; k >= 0; k--) {
                  if (messages[k] && messages[k].role === 'user') return messages[k].text || '';
                }
                return '';
              })();
              const _answerText = String(m.html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
              const _turnIndex = (parseInt(String(m.id).replace(/\D/g, ''), 10) % 10000) || 0;
              return (
                <div className="nac-turn" key={m.id}>
                  <ChatBubble
                    role="assistant"
                    title="Owzy"
                    turnId={m.id}
                    body={useCard ? null : <div dangerouslySetInnerHTML={{ __html: m.html }} />}
                    speechSupported={speechSupported}
                    isSpeaking={speakingMsgId === m.id}
                    onSpeak={() => speakMessage(m.html, m.id)}
                  >
                    {useCard && (
                      <DataSnapshotCard
                        briefing={m.briefing || null}
                        aiHtml={m.html}
                        aiGenerating={!!m.streaming}
                        cols={tableCols}
                        rows={tableRows}
                        chartSpec={m.chartSpec}
                        suggestions={m.suggestions || []}
                        onAsk={(q) => sendChatMessage(q)}
                        onExportXlsx={handleStandardExport}
                        onAiReport={onAiReport}
                        onExplore={(q) => sendChatMessage(q)}
                      />
                    )}
                  </ChatBubble>
                  {!m.streaming && (_answerText || useCard) && (
                    <MessageActions
                      apiBase={API_BASE}
                      xUid={xUid}
                      uUid={uUid}
                      staffUid={staffUid}
                      xBypassUid={xBypassUid}
                      conversationId={m.sessionId || currentSessionId || ''}
                      turnIndex={_turnIndex}
                      question={_q}
                      answer={_answerText}
                      turnId={m.id}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Voice Mode Overlay — Fog + Bubbles */}
        {voiceMode && (
          <div className={`nac-voice-overlay${voiceProcessing ? " nac-voice-overlay--processing" : !recording ? " nac-voice-overlay--connecting" : ""}`}>
            {/* Fog layers */}
            <div className="nac-fog">
              <div className="nac-fog-layer nac-fog-layer--1" />
              <div className="nac-fog-layer nac-fog-layer--2" />
              <div className="nac-fog-layer nac-fog-layer--3" />
            </div>
            {/* Floating bubbles */}
            <div className="nac-bubbles-container">
              <div className="nac-bubble-orb nac-bubble-orb--1" />
              <div className="nac-bubble-orb nac-bubble-orb--2" />
              <div className="nac-bubble-orb nac-bubble-orb--3" />
              <div className="nac-bubble-orb nac-bubble-orb--4" />
              <div className="nac-bubble-orb nac-bubble-orb--5" />
              <div className="nac-bubble-orb nac-bubble-orb--6" />
              <div className="nac-bubble-orb nac-bubble-orb--7" />
            </div>
            <div className="nac-voice-label">
              {voiceProcessing ? "Processing..." : recording ? "Listening..." : "Connecting mic..."}
            </div>
            <div className="nac-voice-sublabel">
              {voiceProcessing ? "Transcribing & submitting..." : recording ? "Stops automatically after you pause" : "Setting up microphone"}
            </div>
            {/* Bottom bar: stop + back to text */}
            {!voiceProcessing && (
              <div className="nac-voice-bottom">
                <button type="button" className="nac-voice-stop" onClick={recording ? stopVoice : exitVoiceMode} title="Stop recording">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="6" y="6" width="12" height="12" rx="3" fill="rgba(255,255,255,0.9)" />
                  </svg>
                </button>
                <button type="button" className="nac-voice-back" onClick={exitVoiceMode} title="Switch to text">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 7h16M4 12h10M4 17h12" />
                  </svg>
                  <span>Text</span>
                </button>
              </div>
            )}
          </div>
        )}

        {/* Input Area */}
        {!voiceMode && (
        <div className="nac-input-area">
          {messages.length <= 1 && (
            <div className="nac-suggestions">
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  type="button"
                  className="nac-suggest-chip"
                  onClick={() => sendChatMessage(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <form className="nac-form" onSubmit={e => { e.preventDefault(); sendChatMessage(inputText); }}>
            <div className="nac-input-wrap">
              <input
                className="nac-input"
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                onKeyDown={handleKeydown}
                placeholder="Ask anything about secondary sales, purchases, primary..."
                autoComplete="off"
              />
            </div>
            <button
              type="button"
              onClick={startVoice}
              disabled={loading}
              className="nac-btn-icon nac-btn-voice"
              title="Switch to voice"
            >
              <span className="nac-mic-icon">
                <span className="nac-mic-ring" />
                <span className="nac-mic-ring" />
                <span className="nac-mic-ring" />
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
              </span>
            </button>
            <button type="submit" disabled={loading || !inputText.trim()} className="nac-btn-icon nac-btn-send" title="Send">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </form>
        </div>
        )}
      </div>{/* end nac-main */}
    </div>
  );
}
