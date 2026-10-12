
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

const autoSaveSession = (uid, sid, messages) => {
  const list = loadSessions(uid);
  const idx = list.findIndex(x => x.id === sid);
  if (idx < 0) return;
  list[idx].messages = [...messages];
  list[idx].updated = new Date().toISOString();
  list[idx].dateKey = list[idx].dateKey || getSessionDateKey(list[idx]);
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
  salesman_name: "Salesman Name",
  ds_code: "Distributor Code",
  ds_name: "Distributor Name",
  dl_code: "Dealer Code",
  dealer_name: "Dealer Name",
  itemcode: "Item Code",
  item_name: "Item Name",
  item_group: "Item Group",
  item_division: "Item Division",
  salesperson_name: "Salesperson Name",
  ds_city: "Distributor City",
  ds_state: "Distributor State",
  ds_zone: "Distributor Zone",
  vendor_code: "Vendor Code",
  vendor_name: "Vendor Name",
  party_name: "Party Name"
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

function filterBlankColumns(cols, rows) {
  if (!Array.isArray(cols) || !Array.isArray(rows) || rows.length === 0) return cols;
  return cols.filter(c => rows.some(r => !isBlankOrNull(r ? r[c] : null)));
}

function suggestAxes(cols, rows) {
  const numeric = [], nonNumeric = [];
  for (const c of cols) {
    (rows.some(r => isNumber(r[c])) ? numeric : nonNumeric).push(c);
  }
  return { x: nonNumeric[0] || cols[0] || "", y: numeric[0] || (cols.length > 1 ? cols[1] : cols[0]) || "" };
}

function escHtml(s = "") {
  return s.toString().replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
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
  if (message.includes('timeout') || message.includes('timed out')) {
    return 'The request took too long. Please try again.';
  }
  if (message.includes('network') || message.includes('failed to fetch') || message.includes('connection')) {
    return 'We could not connect to the service. Please check your connection and try again.';
  }
  if (message.includes('503') || message.includes('could not be stored')) {
    return 'Your response could not be saved safely. Please try again.';
  }
  if (message.includes('500') || message.includes('server error')) {
    return 'The service is temporarily unavailable. Please try again shortly.';
  }
  return fallback;
}

/* ═══════════════════════════════════════════════════════════════════
   MARKDOWN RENDERER — nac-styled output + DMS flag badge
   ═══════════════════════════════════════════════════════════════════ */
function renderMarkdown(text, flag, flagDescription) {
  if (!text) return '<em>No response.</em>';
  const lines = text.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    if (/^\s*\|/.test(lines[i])) {
      const tLines = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) tLines.push(lines[i++]);
      if (tLines.length >= 2) {
        const hdrs = tLines[0].split("|").slice(1, -1).map(c => c.trim());
        const body = /^[\s|:\-]+$/.test(tLines[1]) ? tLines.slice(2) : tLines.slice(1);
        let t = '<div class="nac-md-tbl-wrap"><table class="nac-md-table"><thead><tr>';
        hdrs.forEach(h => { t += "<th>" + escHtml(h) + "</th>"; });
        t += "</tr></thead><tbody>";
        body.forEach(row => {
          const cells = row.split("|").slice(1, -1);
          t += "<tr>" + cells.map(c => "<td>" + escHtml(c.trim()) + "</td>").join("") + "</tr>";
        });
        t += "</tbody></table></div>";
        out.push(t);
      } else {
        tLines.forEach(l => out.push(escHtml(l)));
      }
    } else {
      out.push(lines[i++]);
    }
  }

  let html = out.join("\n");
  const parts = html.split(/(<div class="nac-md-tbl-wrap">[\s\S]*?<\/div>)/);
  html = parts.map(p => p.startsWith('<div class="nac-md-tbl-wrap">') ? p : escHtml(p)).join("");
  html = html
    .replace(/^#{1,2} (.+)$/gm, '<div class="nac-md-h1">$1</div>')
    .replace(/^### (.+)$/gm, '<div class="nac-md-h2">$1</div>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="nac-md-code">$1</code>')
    .replace(/^[-*•] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => '<ul class="nac-md-bullets">' + m + "</ul>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>");
  if (!html.startsWith("<")) html = "<p>" + html + "</p>";

  return '<div class="nac-md-content">' + html + '</div>';
}

function MarkdownContent({ text, flag, flagDescription }) {
  return (
    <div>
      <div className="nac-md-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(text, flag, flagDescription) }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   CHART UTILITIES (ported from Native AI Chat)
   ═══════════════════════════════════════════════════════════════════ */
const VIBRANT_PALETTE = [
  '#3b82f6','#10b981','#f59e0b','#8b5cf6','#ec4899',
  '#06b6d4','#f97316','#6366f1','#14b8a6','#e11d48',
  '#84cc16','#a855f7','#0891b2','#d946ef','#22c55e','#eab308'
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

function buildChartInstance(canvas, type, labels, values, yLabel, showDataLabels = false) {
  const count = labels.length;
  const palette = getMultiColors(count, 0.85);
  const isPie = type === 'pie' || type === 'doughnut';
  const isLine = type === 'line';
  const isSparse = count <= 3;

  const customDatalabelsPlugin = {
    id: 'nacDataLabels',
    afterDatasetsDraw: (chart) => {
      if (!showDataLabels) return;
      const ctx = chart.ctx;
      ctx.save();
      ctx.font = "700 10.5px 'Inter', sans-serif";
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillStyle = '#0f172a';

      chart.data.datasets.forEach((dataset, datasetIndex) => {
        const meta = chart.getDatasetMeta(datasetIndex);
        if (!meta || meta.hidden) return;
        meta.data.forEach((element, index) => {
          const val = dataset.data[index];
          if (val === null || val === undefined || isNaN(val) || val === 0) return;
          const text = nacFmtTick(val);
          if (element && typeof element.tooltipPosition === 'function') {
            const pos = element.tooltipPosition();
            ctx.fillText(text, pos.x, pos.y - 4);
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
        responsive: true, cutout: '65%',
        animation: { duration: 750, easing: 'easeOutQuart' },
        plugins: {
          legend: { position: 'right', labels: { color: '#334155', font: { size: 11, weight: '600' }, usePointStyle: true, padding: 12 } },
          tooltip: { backgroundColor: 'rgba(15,23,42,0.92)', borderColor: 'rgba(59,130,246,0.35)', borderWidth: 1, padding: 12, cornerRadius: 10, titleColor: '#fff', bodyColor: '#e2e8f0' },
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
    gradient.addColorStop(0, 'rgba(59,130,246,0.45)');
    gradient.addColorStop(0.6, 'rgba(139,92,246,0.15)');
    gradient.addColorStop(1, 'rgba(139,92,246,0.01)');
    bg = gradient; border = '#3b82f6';
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
      responsive: true, maintainAspectRatio: true,
      animation: { duration: 750, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15,23,42,0.92)', borderColor: 'rgba(59,130,246,0.35)', borderWidth: 1,
          padding: 12, cornerRadius: 10, titleColor: '#fff', bodyColor: '#e2e8f0',
          callbacks: { label: (ctx) => { const v = ctx.parsed.y ?? ctx.parsed; return (ctx.dataset.label||'') + ': ' + nacFmtTick(v); } }
        },
        datalabels: { display: false },
      },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 10, weight: '500' }, maxRotation: 45, minRotation: 20 }, grid: { color: 'rgba(37,99,235,.05)' } },
        y: { beginAtZero: true, ticks: { color: '#64748b', font: { size: 11, weight: '500' }, callback: nacFmtTick }, grid: { color: 'rgba(37,99,235,.06)' } },
      },
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

function detectChartType(columns, rows) {
  if (!Array.isArray(columns) || !Array.isArray(rows) || rows.length === 0) return "table";
  const numericCols = columns.filter(col => rows.some(row => isNumber(row[col])));
  const dateCols = columns.filter(col => rows.some(row => {
    const val = row[col];
    if (!val) return false;
    return val.toString().match(/^\d{4}-\d{2}-\d{2}/) || val.toString().match(/^\d{1,2}\/\d{1,2}\/\d{4}/);
  }));
  if (numericCols.length === 0) return "table";
  if (rows.length > 200) return "bar";
  if (dateCols.length > 0 && rows.length > 5) return "line";
  if (numericCols.length === 1 && rows.length <= 10) return "pie";
  if (numericCols.length >= 2) return "bar";
  return "table";
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

function ChatBubble({ role, title, body, children, onSpeak, isSpeaking, speechSupported }) {
  const isUser = role === "user";
  const showSpeakBtn = !isUser && speechSupported && !!onSpeak;
  return (
    <div className={`nac-bubble ${isUser ? "nac-bubble--user" : "nac-bubble--assistant"}`}>
      {!isUser && (
        <div className="nac-msg-avatar nac-msg-avatar--assistant" title="DMS AI Chatbot">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z"/>
          </svg>
        </div>
      )}
      <div className={`nac-bubble-content ${isUser ? "nac-bubble-content--user" : "nac-bubble-content--assistant"}`}>
        <div className={`nac-bubble-title ${isUser ? "nac-bubble-title--user" : "nac-bubble-title--assistant"}`}>{title}</div>
        <div className="nac-bubble-body">{body}</div>
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

const THINKING_GROUPS = [
  [
    { icon: "sparkle", text: "Interpreting business requirements..." },
    { icon: "search", text: "Scanning enterprise metrics & database..." },
    { icon: "cpu", text: "Processing key performance indicators..." },
    { icon: "chart", text: "Analyzing growth trends & variances..." },
    { icon: "file", text: "Structuring executive data summary..." },
    { icon: "check", text: "Finalizing your business response..." },
  ],
  [
    { icon: "search", text: "Evaluating sales figures & revenue data..." },
    { icon: "database", text: "Querying target transaction records..." },
    { icon: "cpu", text: "Aggregating performance metrics..." },
    { icon: "chart", text: "Formatting comparative charts..." },
    { icon: "file", text: "Drafting comprehensive summary..." },
    { icon: "check", text: "Polishing your report view..." },
  ],
  [
    { icon: "activity", text: "Reviewing operational parameters..." },
    { icon: "filter", text: "Filtering dataset records & entries..." },
    { icon: "cpu", text: "Calculating category distributions..." },
    { icon: "chart", text: "Mapping key trends & patterns..." },
    { icon: "file", text: "Building clean visualization panels..." },
    { icon: "check", text: "Response ready for review..." },
  ],
  [
    { icon: "search", text: "Examining financial entries & ledgers..." },
    { icon: "database", text: "Pulling period breakdown figures..." },
    { icon: "cpu", text: "Executing summary calculations..." },
    { icon: "chart", text: "Generating period-over-period comparison..." },
    { icon: "file", text: "Preparing structured insights..." },
    { icon: "check", text: "Completing executive view..." },
  ],
  [
    { icon: "users", text: "Accessing account & portfolio records..." },
    { icon: "search", text: "Identifying key segments & totals..." },
    { icon: "cpu", text: "Computing customer metrics..." },
    { icon: "chart", text: "Constructing demographic charts..." },
    { icon: "file", text: "Compiling presentation layout..." },
    { icon: "check", text: "Your analysis is finalized..." },
  ],
  [
    { icon: "sparkle", text: "Synthesizing executive highlights..." },
    { icon: "database", text: "Extracting high-level KPIs..." },
    { icon: "cpu", text: "Processing strategic data points..." },
    { icon: "chart", text: "Visualizing directional trends..." },
    { icon: "file", text: "Assembling executive briefing..." },
    { icon: "check", text: "Report generation complete..." },
  ],
  [
    { icon: "layers", text: "Analyzing inventory & stock metrics..." },
    { icon: "database", text: "Retrieving logistics records..." },
    { icon: "filter", text: "Sorting high-volume inventory items..." },
    { icon: "chart", text: "Plotting distribution breakdowns..." },
    { icon: "file", text: "Organizing summary tables..." },
    { icon: "check", text: "Inventory insights ready..." },
  ],
  [
    { icon: "cpu", text: "Initializing real-time metric engine..." },
    { icon: "search", text: "Locating relevant dataset columns..." },
    { icon: "activity", text: "Performing multi-axis calculations..." },
    { icon: "chart", text: "Generating interactive chart data..." },
    { icon: "file", text: "Structuring clarity summary..." },
    { icon: "check", text: "Data calculations complete..." },
  ],
  [
    { icon: "chart", text: "Evaluating performance benchmarks..." },
    { icon: "database", text: "Cross-referencing historical baselines..." },
    { icon: "activity", text: "Measuring growth vectors..." },
    { icon: "chart", text: "Rendering visual metric charts..." },
    { icon: "file", text: "Formulating key recommendations..." },
    { icon: "check", text: "Growth analysis ready..." },
  ],
  [
    { icon: "sparkle", text: "Engaging AI analytics assistant..." },
    { icon: "search", text: "Exploring relational dataset nodes..." },
    { icon: "cpu", text: "Extracting statistical insights..." },
    { icon: "chart", text: "Formatting dynamic visuals..." },
    { icon: "file", text: "Generating natural language summary..." },
    { icon: "check", text: "Insights ready for display..." },
  ],
];

function RenderIcon({ type }) {
  const props = { width: "13", height: "13", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round", style: { flexShrink: 0, color: "#2563eb" } };
  switch (type) {
    case "sparkle":
      return <svg {...props}><path d="M12 2L9.5 9.5 2 12l7.5 2.5L12 22l2.5-7.5L22 12l-7.5-2.5z"/></svg>;
    case "search":
      return <svg {...props}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>;
    case "cpu":
      return <svg {...props}><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2M9 2v2M15 20v2M9 20v2M20 15h2M20 9h2M2 15h2M2 9h2"/></svg>;
    case "chart":
      return <svg {...props}><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>;
    case "file":
      return <svg {...props}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>;
    case "check":
      return <svg {...props} style={{ flexShrink: 0, color: "#16a34a" }}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>;
    case "database":
      return <svg {...props}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>;
    case "activity":
      return <svg {...props}><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>;
    case "filter":
      return <svg {...props}><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>;
    case "users":
      return <svg {...props}><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>;
    case "layers":
      return <svg {...props}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>;
    default:
      return <svg {...props}><circle cx="12" cy="12" r="10"/></svg>;
  }
}

function ThinkingState() {
  const [groupIndex] = useState(() => Math.floor(Math.random() * THINKING_GROUPS.length));
  const [stepIndex, setStepIndex] = useState(0);

  const steps = THINKING_GROUPS[groupIndex] || THINKING_GROUPS[0];
  const currentStep = steps[stepIndex] || steps[0];

  useEffect(() => {
    const timer = setInterval(() => {
      setStepIndex(prev => (prev + 1) % steps.length);
    }, 1400);
    return () => clearInterval(timer);
  }, [groupIndex, steps.length]);

  return (
    <div className="nac-thinking-container">
      <div className="nac-thinking-header">
        <RenderIcon type={currentStep.icon} />
        <span className="nac-thinking-step-text" key={`${groupIndex}-${stepIndex}`}>
          {currentStep.text}
        </span>
      </div>
      <div className="nac-thinking-bar-wrap">
        <div className="nac-thinking-bar-fill" />
      </div>
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
    if (chartSpec?.chart_type) setChartType(chartSpec.chart_type);
    if (chartSpec?.x && cols.includes(chartSpec.x)) setXCol(chartSpec.x);
    if (chartSpec?.y && cols.includes(chartSpec.y)) setYCol(chartSpec.y);
  }, []);

  const renderChart = useCallback(() => {
    if (!canvasRef.current || !window.Chart) return;
    if (chartRef.current) { try { chartRef.current.destroy(); } catch (_) {} }
    const sortedRows = sortChartRows(rows.slice(0, 50), xCol);
    const labels = sortedRows.map(r => (r[xCol] ?? "").toString());
    const values = sortedRows.map(r => isNumber(r[yCol]) ? Number(r[yCol]) : 0);
    const yLabel = formatColumnLabel(yCol);
    try {
      chartRef.current = buildChartInstance(canvasRef.current, chartType, labels, values, yLabel, showDataLabels);
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
      {rows.length > 0 && (
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
                className={`nac-ct-btn${chartType === t ? " nac-ct-btn--active" : ""}`}
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
          <div className="nac-chart-canvas-wrap">
            <canvas ref={canvasRef} height={140} />
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

.nac-sidebar-toggle {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #475569;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s;
}

.nac-sidebar-toggle:hover {
  background: #e2e8f0;
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

.nac-lang-select-wrap {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  background: #ffffff;
  border: 1.5px solid rgba(37, 99, 235, 0.2);
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 600;
  color: #1e40af;
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.06);
}

.nac-lang-select-wrap:hover {
  background: #f0f5ff;
  border-color: #2563eb;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.12);
}

.nac-lang-icon {
  font-size: 13px;
  line-height: 1;
}

.nac-lang-select {
  background: transparent;
  border: none;
  color: #1e3a8a;
  font-size: 11.5px;
  font-weight: 600;
  font-family: inherit;
  outline: none;
  cursor: pointer;
  padding: 1px 2px;
}

.nac-lang-select option {
  background: #ffffff;
  color: #0f172a;
  font-weight: 500;
  padding: 6px;
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
.nac-status-dot--amber { background: #fbbf24; }
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
  margin-top: 8px;
  border-radius: 8px;
  background: #fff;
  padding: 8px;
}

.nac-chart-canvas-wrap canvas {
  max-width: 100% !important;
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
  background: radial-gradient(circle at 35% 35%, rgba(251,191,36,0.8), rgba(251,191,36,0.12));
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
function DMSAIChat({ isMaximized, user }) {
  // DMS AI backend base URL (override via user.dmsAiBaseUrl if needed).
  // Toggle between environments by commenting/uncommenting the desired URL below.
  // const DMS_AI_BASE_URL = 'https://chatbot.eazydms.com'; // Production (Live)
  const DMS_AI_BASE_URL = 'https://chatbotuatnew.eazydms.com'; // UAT (Testing)
  const API_BASE = String(user?.dmsAiBaseUrl || DMS_AI_BASE_URL).replace(/\/$/, '');

  // Identity is passed as request headers.
  const xUid = user?.['X-UID'] || user?.session_id || localStorage.getItem('dms_session_id') || '';
  const xStaffUid = user?.['X-Staff-UID'] || user?.['X-UID-STAFF'] || user?.userid || user?.assigned_user_id || user?.['U-UID'] || '';
  const xBypassUid = user?.['x-bypass-uid'] || 'true';

  // fetchJson — prepends API_BASE, attaches identity headers, adds timeout + retry/abort wrapper.
  const fetchJson = async (url, opts = {}) => {
    const o = { ...opts };
    const effectiveStaffUid = staffUid || xStaffUid || localStorage.getItem('dms_analytics_uid') || '';
    const effectiveSessionUid = xUid;

    const headers = {
      'Content-Type': 'application/json',
      ...(effectiveSessionUid ? { 'x-uid': effectiveSessionUid, 'X-UID': effectiveSessionUid } : {}),
      ...(effectiveStaffUid ? { 'X-Staff-UID': effectiveStaffUid, 'u-uid': effectiveStaffUid, 'x_staff_uid': effectiveStaffUid } : {}),
      ...(xBypassUid ? { 'x-bypass-uid': xBypassUid } : { 'x-bypass-uid': 'true' }),
      ...(o.headers || {})
    };
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
    const effectiveStaffUid = staffUid || xStaffUid || localStorage.getItem('dms_analytics_uid') || '';
    if (!effectiveStaffUid && !xUid) return null;
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

  // Output Language Preference State (Encrypted on backend via /api/prefs/output-lang)
  const [outputLang, setOutputLang] = useState(() => {
    return localStorage.getItem(`dms_output_lang_${staffUid}`) || localStorage.getItem('dms_output_lang') || 'auto';
  });
  const [outputLangs, setOutputLangs] = useState([
    { code: 'auto', label: '🌐 Auto — match question' },
    { code: 'en-IN', label: 'English' },
    { code: 'hi-IN', label: 'हिन्दी Hindi' },
    { code: 'ta-IN', label: 'தமிழ் Tamil' },
    { code: 'te-IN', label: 'తెలుగు Telugu' },
    { code: 'kn-IN', label: 'ಕನ್ನಡ Kannada' },
    { code: 'ml-IN', label: 'മലയാളം Malayalam' },
    { code: 'mr-IN', label: 'मराठी Marathi' },
    { code: 'bn-IN', label: 'বাংলা Bengali' },
    { code: 'gu-IN', label: 'ગુજરાતી Gujarati' },
    { code: 'pa-IN', label: 'ਪੰਜਾਬੀ Punjabi' },
    { code: 'ur-IN', label: 'اردو Urdu' }
  ]);

  // Sync output language preference with server-side encrypted storage
  useEffect(() => {
    if (!staffUid) return;
    let isMounted = true;
    fetchJson(`/api/prefs/output-lang?uid=${encodeURIComponent(staffUid)}`)
      .then(res => {
        if (isMounted && res.ok && res.data?.lang) {
          const l = res.data.lang;
          setOutputLang(l);
          localStorage.setItem('dms_output_lang', l);
          localStorage.setItem(`dms_output_lang_${staffUid}`, l);
          if (Array.isArray(res.data.available_langs) && res.data.available_langs.length > 0) {
            setOutputLangs(res.data.available_langs);
          }
        }
      })
      .catch(err => console.warn('[DMSAIChat] Failed to fetch encrypted output-lang:', err));
    return () => { isMounted = false; };
  }, [staffUid]);

  const handleLanguageChange = async (newLang) => {
    setOutputLang(newLang);
    localStorage.setItem('dms_output_lang', newLang);
    if (staffUid) localStorage.setItem(`dms_output_lang_${staffUid}`, newLang);
    try {
      await fetchJson('/api/prefs/output-lang', {
        method: 'POST',
        body: JSON.stringify({ uid: staffUid, lang: newLang })
      });
    } catch (err) {
      console.warn('[DMSAIChat] Failed to save encrypted output-lang:', err);
    }
  };

  // Chat/Messages State
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      html: '<p><strong>DMS AI Chatbot</strong> is active. You can request queries or summaries regarding your <strong>secondary sales</strong>, <strong>purchases</strong>, or <strong>primary sales</strong> metrics.</p>'
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

  // Modal (AI Excel Report)
  const [modalConfig, setModalConfig] = useState(null);
  const [aiError, setAiError] = useState('');
  const [aiLoading, setAiLoading] = useState(false);

  // Inline renaming
  const [renamingId, setRenamingId] = useState(null);
  const [renameText, setRenameText] = useState('');

  // Voice recording — raw PCM capture + silence detection + server-side transcription
  // (ported from NativeAIChat.jsx; replaces the old browser SpeechRecognition mic toggle)
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

  function exitVoiceMode() {
    // Tell RN to cancel voice if in WebView
    if (isInReactNativeWebView()) {
      try { window.ReactNativeWebView.postMessage(JSON.stringify({ type: "voice-cancel" })); } catch (_) {}
    }
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
        body: JSON.stringify({ audio_b64: btoa(binary), sample_rate_hz: 16000, sample_width: 2 }),
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
      const resp = await fetchJson('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          userid: uUid || staffUid,
          message: messageText,
          session_id: currentSessionId,
          history: conversationContext.current.slice(-10),
          name: user?.firstName,
          email: user?.email
        })
      });

      const data = resp.data || {};

      if (data.session_id) setCurrentSessionId(data.session_id);

      if (!resp.ok) {
        const serverMsg = data.error || data.message || data.detail || `Server error (${resp.status})`;
        throw new Error(serverMsg);
      }

      const answer = data.answer || 'No response could be parsed.';
      if (!data.answer) {
        console.warn('[DMSAIChat] API response missing answer field. Full response:', data);
      }
      const flag = data.flag || null;
      const flagDescription = data.flag_description || null;

      // Extract data query details for Excel export
      let sourceRows = data.rows || [];
      let sourceCols = data.columns || [];
      if (sourceRows.length > 0) {
        lastExecutionData.current = { columns: sourceCols, rows: sourceRows };
      }

      const chartSpec = (data.chart_spec && data.chart_spec.chart_type) ? data.chart_spec : null;

      // Replace loading bubble with fully structured response
      setMessages(prev => prev.map(m => m.id === loadingId ? {
        id: 'ai-' + Date.now(),
        role: 'assistant',
        html: renderMarkdown(answer, flag, flagDescription),
        chartSpec,
        chartRows: chartSpec ? (chartSpec.rows || sourceRows) : [],
        chartCols: chartSpec ? (chartSpec.columns || sourceCols) : [],
        hasData: sourceRows.length > 0
      } : m));

      // Append context N turns
      conversationContext.current = [
        ...conversationContext.current,
        { role: 'user', content: messageText },
        { role: 'assistant', content: answer }
      ].slice(-20);

      // Persist session history
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

  // ── Conversation Lifecycle ───────────────────────────────────
  const startNewConversation = (uidVal = staffUid) => {
    if (!uidVal) return;
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        html: '<p>👋 Welcome to <strong>DMS AI natural language analytics</strong>. Ask me anything about your <strong>secondary sales</strong>, <strong>purchases</strong>, or <strong>primary sales</strong> metrics.</p>'
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
        rebuiltMessages.push({
          id: 'rebuilt-' + index,
          role: 'assistant',
          html: renderMarkdown(m.content)
        });
      }
    });

    setMessages(rebuiltMessages.length > 0 ? rebuiltMessages : [
      {
        id: 'welcome',
        role: 'assistant',
        html: '<p>👋 Welcome back. Let\'s continue our conversation.</p>'
      }
    ]);
    conversationContext.current = session.messages.slice();
    setCurrentSessionId(session.id);
    lastExecutionData.current = null;
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
    metadata.textContent = `DMS AI Report — Generated: ${new Date().toLocaleString('en-IN')} | User ID: ${getSelectedStaffName()}`;
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
            <button className="nac-sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)} title="Chat history">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div>
              <div className="nac-tb-title" style={{ fontWeight: 700, letterSpacing: "-0.01em" }}>DMS AI Chatbot</div>
              <div className="nac-tb-status">
                <span className="nac-status-dot nac-status-dot--green" />
                Online - Get your business insights now
              </div>
            </div>
          </div>
          <div className="nac-toolbar-btns">
            <div className="nac-lang-select-wrap" title="Response Language Preference (Encrypted & Saved to Profile)">
              <span className="nac-lang-icon">🌐</span>
              <select
                className="nac-lang-select"
                value={outputLang}
                onChange={e => handleLanguageChange(e.target.value)}
              >
                {outputLangs.map(l => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              className="nac-tbtn"
              onClick={() => {
                setModalConfig({
                  title: "New Conversation",
                  message: "Start a fresh chat session?",
                  onConfirm: () => { setModalConfig(null); startNewConversation(); },
                });
              }}
              title="New conversation"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12h14"/>
              </svg>
              New Chat
            </button>
          </div>
        </div>

        {/* Chat */}
        <div className="nac-chat-area" ref={chatRef}>
          <div className="nac-messages">
            {messages.map(m => {
              if (m.role === 'user') {
                return (
                  <ChatBubble key={m.id} role="user" title="You" body={m.text} />
                );
              }
              if (m.loadingPlaceholder) {
                return (
                  <div className="nac-bubble nac-bubble--assistant" key={m.id}>
                    <div className="nac-msg-avatar nac-msg-avatar--assistant nac-msg-avatar--thinking" title="DMS AI Chatbot is thinking...">
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
              const tableCols = hasChart && m.chartCols && m.chartCols.length ? m.chartCols : (m.hasData ? (lastExecutionData.current?.columns || []) : []);
              const tableRows = hasChart ? m.chartRows : (m.hasData ? (lastExecutionData.current?.rows || []) : []);
              return (
                <ChatBubble
                  key={m.id}
                  role="assistant"
                  title="DMS AI Chatbot"
                  body={<div dangerouslySetInnerHTML={{ __html: m.html }} />}
                  speechSupported={speechSupported}
                  isSpeaking={speakingMsgId === m.id}
                  onSpeak={() => speakMessage(m.html, m.id)}
                >
                  {hasChart && (
                    <ResultTable
                      cols={tableCols}
                      rows={tableRows}
                      truncated={false}
                      chartSpec={m.chartSpec}
                      onExportXlsx={handleStandardExport}
                      onAiReport={() => {
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
                      }}
                    />
                  )}
                </ChatBubble>
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
