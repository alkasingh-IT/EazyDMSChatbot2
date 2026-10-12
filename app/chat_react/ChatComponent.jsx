const { useState, useEffect, useRef } = React;

/* ═══════════════════════════════════════════════════════════════════
   SESSION HELPERS (localStorage, matches DMS app.js)
   ═══════════════════════════════════════════════════════════════════ */
const SESS_PREFIX = 'dmsSessions_';
const getSessKey = (uid) => SESS_PREFIX + (uid || 'anon');

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
   MARKDOWN AND TABULAR CONTENT RENDERER
   ═══════════════════════════════════════════════════════════════════ */
function renderMarkdown(text, flag, flagDescription) {
  if (!text) return '<em>No response.</em>';
  const lines = text.split('\n');
  const processed = [];
  let i = 0;
  
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*\|/.test(line)) {
      const tableLines = [];
      while (i < lines.length && /^\s*[\|]/.test(lines[i])) {
        tableLines.push(lines[i++]);
      }
      if (tableLines.length >= 2) {
        const headers = tableLines[0].split('|').slice(1, -1).map(c => c.trim());
        const bodyLines = /^[\s|:\-]+$/.test(tableLines[1]) ? tableLines.slice(2) : tableLines.slice(1);
        let tHtml = '<div class="dms-tbl-wrap"><table class="dms-md-table"><thead><tr>';
        headers.forEach(h => {
          tHtml += `<th>${h}</th>`;
        });
        tHtml += '</tr></thead><tbody>';
        bodyLines.forEach(row => {
          const cells = row.split('|').slice(1, -1);
          tHtml += '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
        });
        tHtml += '</tbody></table></div>';
        processed.push(tHtml);
      } else {
        tableLines.forEach(l => processed.push(l));
      }
    } else {
      processed.push(lines[i++]);
    }
  }

  let html = processed.join('\n')
    .replace(/^#{1,2} (.+)$/gm, '<div class="dms-sec-head">$1</div>')
    .replace(/^### (.+)$/gm, '<div class="dms-sec-sub">$1</div>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="dms-code-inline">$1</code>')
    .replace(/^[-*•] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul class="dms-bullets">${m}</ul>`)
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br>');

  if (!html.startsWith('<')) html = `<p>${html}</p>`;
  
  return '<div class="dms-ai-text">' + html + '</div>';
}

/* ═══════════════════════════════════════════════════════════════════
   CHART COMPONENT
   ═══════════════════════════════════════════════════════════════════ */
const PALETTE = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#14b8a6', '#f43f5e', '#6366f1'];

function DMSChart({ spec, rows, chartReady }) {
  const canvasRef = useRef(null);
  const chartInstance = useRef(null);
  const [currentType, setCurrentType] = useState(spec.chart_type || 'bar');
  const availableTypes = ['bar', 'line', 'pie'];

  useEffect(() => {
    if (!chartReady || !canvasRef.current || !rows || !rows.length) return;
    if (chartInstance.current) {
      chartInstance.current.destroy();
      chartInstance.current = null;
    }

    const xKey = spec.x;
    const yKey = spec.y;
    const cleanRows = rows.slice(0, 30);
    const labels = cleanRows.map(r => String(r[xKey] ?? ''));
    const values = cleanRows.map(r => parseFloat(r[yKey]) || 0);

    const isPie = currentType === 'pie';
    const isLine = currentType === 'line';

    const ctx = canvasRef.current.getContext('2d');
    chartInstance.current = new window.Chart(ctx, {
      type: isPie ? 'doughnut' : currentType,
      data: {
        labels,
        datasets: [{
          label: (yKey || 'Value').replace(/_/g, ' ').toUpperCase(),
          data: values,
          backgroundColor: isPie 
            ? PALETTE.slice(0, cleanRows.length) 
            : (isLine ? 'rgba(59, 130, 246, 0.12)' : 'rgba(59, 130, 246, 0.75)'),
          borderColor: isPie 
            ? PALETTE.slice(0, cleanRows.length).map(c => c + 'dd') 
            : '#3b82f6',
          borderWidth: isPie ? 0 : 2,
          borderRadius: currentType === 'bar' ? 6 : 0,
          fill: isLine,
          tension: 0.35,
          pointBackgroundColor: '#2563eb',
          pointRadius: isLine ? 4 : 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: isPie,
            position: 'right',
            labels: { color: '#475569', font: { family: 'Inter', size: 10 } }
          },
          tooltip: {
            backgroundColor: '#0f172a',
            titleColor: '#fff',
            bodyColor: '#cbd5e1',
            padding: 8,
            cornerRadius: 6
          }
        },
        scales: isPie ? {} : {
          x: {
            ticks: { color: '#64748b', font: { size: 9 }, maxRotation: 45 },
            grid: { color: 'rgba(59, 130, 246, 0.05)' }
          },
          y: {
            beginAtZero: true,
            ticks: { color: '#64748b', font: { size: 10 } },
            grid: { color: 'rgba(59, 130, 246, 0.05)' }
          }
        }
      }
    });

    return () => {
      if (chartInstance.current) {
        chartInstance.current.destroy();
        chartInstance.current = null;
      }
    };
  }, [currentType, chartReady, rows, spec]);

  return (
    <div className="dms-chart-card">
      <div className="dms-chart-header">
        <span className="dms-chart-title">📈 Data Visualizer</span>
        <div className="dms-chart-type-tabs">
          {availableTypes.map(t => (
            <button 
              key={t} 
              className={`dms-chart-tab ${t === currentType ? 'active' : ''}`}
              onClick={() => setCurrentType(t)}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="dms-chart-canvas-wrap">
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   AI SMART REPORT MODAL
   ═══════════════════════════════════════════════════════════════════ */
const PRESETS = [
  { label: '📊 Summary Sheet', desc: 'Group & calculate sums', prompt: 'Group the dataset by the primary category field and compute sum and averages for all numeric fields' },
  { label: '📅 Chronological', desc: 'Sort & format by date', prompt: 'Sort all entries chronologically by the date field and highlight entries with large changes' },
  { label: '🏪 Top Performers', desc: 'Rank & highlight top 10', prompt: 'Rank the top 10 rows by sales value, highlight top 3 in green, and add a bottom total row' },
  { label: '⚠️ Outlier Highlights', desc: 'Highlight low/empty values', prompt: 'Highlight rows in soft red where quantities are zero or values are below average' }
];

function AIReportModal({ isOpen, onClose, onGenerate, loading, error }) {
  const [prompt, setPrompt] = useState('');
  if (!isOpen) return null;

  return (
    <div className="dms-modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="dms-modal">
        <div className="dms-modal-header">
          <div className="dms-modal-brand">
            <div className="dms-modal-icon">⚙️</div>
            <div>
              <div className="dms-modal-title">AI Smart Excel Generator</div>
              <div className="dms-modal-sub">Tell the AI how to format and sort your export</div>
            </div>
          </div>
          <button className="dms-modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="dms-modal-body">
          <textarea
            className="dms-modal-textarea"
            rows={4}
            placeholder="e.g., Sort by billed value descending, highlight top 5 items green, format currency..."
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
          />
          <div className="dms-modal-presets">
            {PRESETS.map(p => (
              <button key={p.label} className="dms-preset-card" onClick={() => setPrompt(p.prompt)}>
                <span className="dms-preset-title">{p.label}</span>
                <span className="dms-preset-desc">{p.desc}</span>
              </button>
            ))}
          </div>
          {error && <div className="dms-modal-error">⚠️ {error}</div>}
          <div className="dms-modal-footer">
            <button className="dms-btn dms-btn-secondary" onClick={onClose}>Cancel</button>
            <button 
              className="dms-btn dms-btn-primary" 
              onClick={() => onGenerate(prompt)}
              disabled={loading || !prompt.trim()}
            >
              {loading ? 'Processing...' : 'Generate AI Smart Sheet'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   CSS STYLES
   ═══════════════════════════════════════════════════════════════════ */
const INJECTED_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');

:root {
  --dms-primary: #2563eb;
  --dms-primary-dark: #1d4ed8;
  --dms-bg: #f1f5f9;
  --dms-panel: #ffffff;
  --dms-border: #e2e8f0;
  --dms-text: #0f172a;
  --dms-text-muted: #475569;
  --dms-font: 'Plus Jakarta Sans', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.dms-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: var(--dms-bg);
  color: var(--dms-text);
  font-family: var(--dms-font);
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
}

.dms-root *, .dms-root *::before, .dms-root *::after {
  box-sizing: inherit;
}

/* Staff Selector Bar */
.dms-staff-header {
  display: none !important;
}

.dms-staff-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--dms-primary);
  letter-spacing: 0.08em;
}

.dms-staff-select {
  background: var(--dms-panel);
  border: 1px solid var(--dms-border);
  color: var(--dms-text);
  font-size: 13px;
  font-family: var(--dms-font);
  border-radius: 6px;
  padding: 6px 12px;
  outline: none;
  cursor: pointer;
  max-width: 280px;
  transition: border-color 0.2s;
}

.dms-staff-select:focus {
  border-color: var(--dms-primary);
}

.dms-staff-badge {
  font-size: 11px;
  color: var(--dms-text-muted);
  margin-left: auto;
  background: rgba(59, 130, 246, 0.1);
  padding: 3px 8px;
  border-radius: 20px;
  border: 1px solid rgba(59, 130, 246, 0.2);
}

/* Toolbar */
.dms-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  background: var(--dms-panel);
  border-bottom: 1px solid var(--dms-border);
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.dms-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dms-logo {
  font-size: 20px;
}

.dms-brand-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--dms-text);
}

.dms-brand-status {
  font-size: 10px;
  color: #10b981;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 1px;
}

.dms-status-dot {
  width: 5px;
  height: 5px;
  background: #10b981;
  border-radius: 50%;
  animation: dmsPulse 1.5s infinite;
}

@keyframes dmsPulse {
  0% { transform: scale(0.9); opacity: 0.6; }
  50% { transform: scale(1.1); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.6; }
}

.dms-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.dms-btn-tool {
  background: var(--dms-panel);
  border: 1px solid var(--dms-border);
  color: var(--dms-text);
  font-size: 11.5px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: var(--dms-font);
  transition: all 0.15s ease;
}

.dms-btn-tool:hover {
  background: var(--dms-bg);
  border-color: var(--dms-text-muted);
}

.dms-btn-tool.active {
  background: rgba(59, 130, 246, 0.08);
  border-color: var(--dms-primary);
  color: var(--dms-primary);
}

.dms-btn-tool.export {
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.4);
}

.dms-btn-tool.export:hover {
  background: rgba(16, 185, 129, 0.06);
  border-color: #10b981;
}

/* Layout Containers */
.dms-main-container {
  display: flex;
  flex: 1;
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
}

.dms-content-area {
  display: flex;
  flex-direction: column;
  flex: 1;
  height: 100%;
  overflow: hidden;
}

/* Sidebar History Drawer */
.dms-history-drawer {
  width: 270px;
  background: var(--dms-panel);
  border-right: 1px solid var(--dms-border);
  display: flex;
  flex-direction: column;
  transition: width 0.22s cubic-bezier(0.4, 0, 0.2, 1), margin-left 0.22s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  flex-shrink: 0;
}

.dms-history-drawer.open {
  width: 270px;
  margin-left: 0;
}

.dms-history-drawer:not(.open) {
  width: 0;
  margin-left: -1px;
  border-right-color: transparent;
}

@media (max-width: 768px) {
  .dms-main-container {
    position: relative;
  }
  .dms-history-drawer {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 100;
    box-shadow: 4px 0 20px rgba(0,0,0,0.08);
  }
  .dms-history-drawer.open {
    width: 270px;
    margin-left: 0;
  }
  .dms-history-drawer:not(.open) {
    width: 0;
    margin-left: -271px;
  }
}

.dms-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: var(--dms-bg);
  border-bottom: 1px solid var(--dms-border);
}

.dms-drawer-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--dms-text);
}

.dms-btn-new-chat {
  background: var(--dms-primary);
  color: #fff;
  border: none;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
  cursor: pointer;
  font-family: var(--dms-font);
}

.dms-btn-new-chat:hover {
  background: var(--dms-primary-dark);
}

.dms-drawer-close {
  background: transparent;
  border: none;
  color: var(--dms-text-muted);
  font-size: 18px;
  cursor: pointer;
}

.dms-drawer-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.dms-history-item {
  padding: 10px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.15s;
  position: relative;
}

.dms-history-item:hover {
  background: rgba(0, 0, 0, 0.03);
}

.dms-history-item.active {
  background: rgba(59, 130, 246, 0.06);
  border-left-color: var(--dms-primary);
}

.dms-hist-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dms-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
}

.dms-history-item.active .dms-hist-title {
  color: var(--dms-primary);
}

.dms-hist-meta {
  font-size: 10px;
  color: var(--dms-text-muted);
}

.dms-hist-actions {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  display: none;
  gap: 2px;
}

.dms-history-item:hover .dms-hist-actions {
  display: flex;
}

.dms-btn-action {
  background: var(--dms-panel);
  border: 1px solid var(--dms-border);
  color: var(--dms-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  font-size: 10px;
}

.dms-btn-action:hover {
  color: var(--dms-text);
  background: var(--dms-bg);
}

.dms-btn-action.delete:hover {
  background: #ef4444;
  border-color: #ef4444;
  color: #fff;
}

.dms-rename-input {
  width: calc(100% - 30px);
  background: var(--dms-panel);
  border: 1px solid var(--dms-primary);
  border-radius: 4px;
  color: var(--dms-text);
  padding: 2px 6px;
  font-size: 12px;
  outline: none;
}

/* Batch Panel */
.dms-batch-panel {
  background: #eef2ff;
  border-bottom: 1px solid rgba(99, 102, 241, 0.15);
  padding: 12px 18px;
  flex-shrink: 0;
}

.dms-batch-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.dms-batch-title {
  font-size: 12px;
  font-weight: 700;
  color: #312e81;
}

.dms-batch-desc {
  font-size: 10px;
  color: #4f46e5;
}

.dms-batch-textarea {
  width: 100%;
  background: var(--dms-panel);
  border: 1px solid rgba(99, 102, 241, 0.25);
  border-radius: 6px;
  color: var(--dms-text);
  font-size: 12px;
  font-family: var(--dms-font);
  padding: 8px 10px;
  outline: none;
  resize: vertical;
  min-height: 70px;
}

.dms-batch-textarea:focus {
  border-color: var(--dms-primary);
}

.dms-batch-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}

.dms-batch-progress {
  font-size: 11px;
  color: #312e81;
}

.dms-btn-batch-run {
  background: #4f46e5;
  color: #fff;
  border: none;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}

.dms-btn-batch-run:hover {
  background: #4338ca;
}

/* Chat Canvas */
.dms-messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--dms-bg);
}


.dms-msg {
  display: flex;
  flex-direction: column;
  max-width: 80%;
  animation: dmsFadeIn 0.2s ease-out;
}

@keyframes dmsFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.dms-msg.user {
  align-self: flex-end;
}

.dms-msg-user-bubble {
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #fff;
  padding: 10px 15px;
  border-radius: 12px 12px 2px 12px;
  font-size: 13.5px;
  line-height: 1.5;
  font-weight: 500;
  box-shadow: 0 4px 15px rgba(37, 99, 235, 0.2);
  white-space: pre-wrap;
  word-break: break-word;
}

.dms-msg.ai {
  align-self: flex-start;
  max-width: 90%;
}

.dms-ai-identity {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.dms-ai-avatar {
  background: var(--dms-primary);
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
}

.dms-ai-name {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--dms-primary);
}

.dms-ai-bubble {
  background: var(--dms-panel);
  border: 1px solid var(--dms-border);
  padding: 12px 16px;
  border-radius: 2px 12px 12px 12px;
  font-size: 13.5px;
  line-height: 1.6;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}

.dms-ai-text p {
  margin: 0 0 10px;
}

.dms-ai-text p:last-child {
  margin-bottom: 0;
}

.dms-sec-head {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--dms-primary);
  letter-spacing: 0.05em;
  margin: 14px 0 6px;
  padding-bottom: 3px;
  border-bottom: 1px solid var(--dms-border);
}

.dms-sec-sub {
  font-weight: 700;
  font-size: 12px;
  margin: 10px 0 4px;
  color: var(--dms-text);
}

.dms-bullets {
  list-style: none;
  padding: 0;
  margin: 0 0 10px 0;
}

.dms-bullets li {
  position: relative;
  padding-left: 12px;
  margin-bottom: 3px;
  font-size: 13px;
}

.dms-bullets li::before {
  content: "■";
  color: var(--dms-primary);
  font-size: 8px;
  position: absolute;
  left: 0;
  top: 1px;
}

.dms-code-inline {
  background: #e2e8f0;
  color: #0f766e;
  padding: 1px 4px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
}

.dms-flags {
  margin-top: 10px;
  background: rgba(59, 130, 246, 0.05);
  border: 1px solid rgba(59, 130, 246, 0.15);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 10.5px;
  color: var(--dms-text-muted);
}

.dms-flags code {
  color: var(--dms-primary);
  background: rgba(59, 130, 246, 0.08);
  padding: 1px 4px;
  border-radius: 4px;
}

/* Embedded Table */
.dms-tbl-wrap {
  margin: 10px 0;
  overflow-x: auto;
  border: 1px solid var(--dms-border);
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.02);
}

.dms-md-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: var(--dms-panel);
}

.dms-md-table th {
  background: #f8fafc;
  color: var(--dms-text-muted);
  font-weight: 600;
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--dms-border);
  font-size: 11px;
  text-transform: uppercase;
}

.dms-md-table td {
  padding: 7px 12px;
  border-bottom: 1px solid var(--dms-border);
  color: var(--dms-text);
}

.dms-md-table tr:nth-child(even) td {
  background: #f8fafc;
}

/* Loading bubble */
.dms-msg-loading {
  display: flex;
  gap: 4px;
  padding: 4px 6px;
  align-items: center;
}

.dms-dot {
  width: 6px;
  height: 6px;
  background: var(--dms-primary);
  border-radius: 50%;
  animation: dmsDotBounce 1.4s infinite ease-in-out;
}

.dms-dot:nth-child(2) { animation-delay: 0.2s; }
.dms-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes dmsDotBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.dms-batch-divider {
  align-self: center;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  color: #2563eb;
  background: #dbeafe;
  padding: 3px 12px;
  border-radius: 20px;
  letter-spacing: 0.06em;
  margin: 8px 0;
}

/* Suggestion Chips */
.dms-input-dock {
  background: var(--dms-panel);
  border-top: 1px solid var(--dms-border);
  padding: 12px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  box-shadow: 0 -2px 10px rgba(0,0,0,0.02);
}

.dms-suggestions-bar {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.dms-suggestions-bar::-webkit-scrollbar {
  display: none;
}

.dms-chip {
  background: var(--dms-bg);
  border: 1px solid var(--dms-border);
  color: var(--dms-text-muted);
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.dms-chip:hover {
  border-color: var(--dms-primary);
  color: var(--dms-primary);
  background: rgba(59, 130, 246, 0.05);
}

/* Input Row */
.dms-input-row {
  display: flex;
  gap: 8px;
  align-items: center;
  background: var(--dms-bg);
  border: 1px solid var(--dms-border);
  border-radius: 8px;
  padding: 4px 4px 4px 12px;
  transition: border-color 0.2s;
}

.dms-input-row:focus-within {
  border-color: var(--dms-primary);
  background: var(--dms-panel);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}


.dms-text-area {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--dms-text);
  font-size: 13.5px;
  outline: none;
  font-family: var(--dms-font);
  resize: none;
  height: 24px;
  line-height: 24px;
}

.dms-btn-send {
  background: var(--dms-primary);
  color: #fff;
  border: none;
  font-family: var(--dms-font);
  font-weight: 600;
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.dms-btn-send:hover {
  background: var(--dms-primary-dark);
}

.dms-btn-voice {
  background: var(--dms-panel);
  border: 1px solid var(--dms-border);
  border-radius: 6px;
  cursor: pointer;
  padding: 5px 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--dms-text-muted);
  transition: all 0.15s ease;
}

.dms-btn-voice:hover {
  background: var(--dms-bg);
  color: var(--dms-primary);
  border-color: var(--dms-primary);
}

.dms-btn-voice.recording {
  background: #fee2e2;
  border-color: #ef4444;
  color: #ef4444;
  animation: dmsVoicePulse 1.2s infinite;
}

@keyframes dmsVoicePulse {
  0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.3); }
  70% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}

/* Modal */
.dms-modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.65);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.dms-modal {
  background: var(--dms-panel);
  border: 1px solid var(--dms-border);
  border-radius: 12px;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.05), 0 10px 10px -5px rgba(0, 0, 0, 0.02);
  overflow: hidden;
}

.dms-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  background: var(--dms-bg);
  border-bottom: 1px solid var(--dms-border);
}

.dms-modal-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dms-modal-icon {
  font-size: 20px;
}

.dms-modal-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--dms-text);
}

.dms-modal-sub {
  font-size: 10px;
  color: var(--dms-text-muted);
}

.dms-modal-close {
  background: transparent;
  border: none;
  color: var(--dms-text-muted);
  font-size: 20px;
  cursor: pointer;
}

.dms-modal-body {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dms-modal-textarea {
  width: 100%;
  background: var(--dms-bg);
  border: 1px solid var(--dms-border);
  border-radius: 8px;
  color: var(--dms-text);
  padding: 10px;
  font-size: 12.5px;
  font-family: var(--dms-font);
  outline: none;
}

.dms-modal-presets {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.dms-preset-card {
  background: var(--dms-bg);
  border: 1px solid var(--dms-border);
  border-radius: 8px;
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}

.dms-preset-card:hover {
  border-color: var(--dms-primary);
  background: rgba(59, 130, 246, 0.04);
}

.dms-preset-title {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--dms-text);
}

.dms-preset-desc {
  display: block;
  font-size: 9.5px;
  color: var(--dms-text-muted);
  margin-top: 1px;
}

.dms-modal-error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #ef4444;
  padding: 8px;
  border-radius: 6px;
  font-size: 11.5px;
}

.dms-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}

.dms-btn {
  font-family: var(--dms-font);
  font-size: 12px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
}

.dms-btn-secondary {
  background: #1f2937;
  border: 1px solid var(--dms-border);
  color: var(--dms-text-muted);
}

.dms-btn-secondary:hover {
  background: #374151;
  color: var(--dms-text);
}

.dms-btn-primary {
  background: var(--dms-primary);
  border: none;
  color: #fff;
}

.dms-btn-primary:hover {
  background: var(--dms-primary-dark);
}

.dms-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Embedded inline excel action */
.dms-inline-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.dms-inline-label {
  font-size: 10px;
  color: var(--dms-text-muted);
}

.dms-inline-button {
  background: transparent;
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #10b981;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10.5px;
  cursor: pointer;
}

.dms-inline-button:hover {
  background: rgba(16, 185, 129, 0.05);
}

.dms-inline-button.smart {
  color: var(--dms-primary);
  border-color: rgba(59, 130, 246, 0.3);
}

.dms-inline-button.smart:hover {
  background: rgba(59, 130, 246, 0.05);
}

/* Active Chart component styling inside bubble */
.dms-chart-card {
  margin-top: 10px;
  background: #111827;
  border: 1px solid var(--dms-border);
  border-radius: 8px;
  padding: 12px;
}

.dms-chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.dms-chart-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--dms-text-muted);
}

.dms-chart-type-tabs {
  display: flex;
  gap: 2px;
}

.dms-chart-tab {
  background: transparent;
  border: none;
  color: var(--dms-text-muted);
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  cursor: pointer;
}

.dms-chart-tab.active {
  color: var(--dms-primary);
}

.dms-chart-canvas-wrap {
  position: relative;
  height: 140px;
  width: 100%;
}

@media print {
  .dms-staff-header, .dms-toolbar, .dms-input-dock, .dms-history-drawer, .dms-batch-panel {
    display: none !important;
  }
  .dms-messages-area {
    background: #fff !important;
    overflow: visible !important;
  }
}

@media (max-width: 480px) {
  .dms-input-dock {
    padding: 8px 12px;
  }
  .dms-suggestions-bar {
    gap: 4px;
  }
  .dms-chip {
    padding: 3px 8px;
    font-size: 10.5px;
  }
  .dms-messages-area {
    padding: 12px 14px;
  }
  .dms-msg {
    max-width: 95%;
  }
}
`;

function injectCSSOnce() {
  if (document.getElementById('dms-chat-component-css')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'dms-chat-component-css';
  styleEl.textContent = INJECTED_CSS;
  document.head.appendChild(styleEl);
}

/* ═══════════════════════════════════════════════════════════════════
   CHIP SUGGESTIONS
   ═══════════════════════════════════════════════════════════════════ */
const SUGGESTIONS = [
  'Secondary sales this month',
  'Compare primary vs secondary sales',
  'Show purchase trends for last 6 months',
  'What is my secondary sales growth vs last month?',
  'Top 5 items by secondary sales this quarter',
  'Which dealers did I sell to most this month?'
];

/* ═══════════════════════════════════════════════════════════════════
   MAIN EXPORTED REACT COMPONENT
   ═══════════════════════════════════════════════════════════════════ */
function DMSChatComponent() {
  // Staff Selection States
  const [staffList, setStaffList] = useState([]);
  const [staffUid, setStaffUid] = useState(() => localStorage.getItem('dms_analytics_uid') || '');
  const [staffLoading, setStaffLoading] = useState(false);

  // Chat/Messages State
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      html: '<p><strong>DMS Analytics assistant</strong> is active. You can request queries or summaries regarding your <strong>secondary sales</strong>, <strong>purchases</strong>, or <strong>primary sales</strong> metrics.</p>'
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);

  // Chat Session States
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const conversationContext = useRef([]);
  const lastExecutionData = useRef(null);

  // Drawer & Panels
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isBatchOpen, setIsBatchOpen] = useState(false);
  const [batchInput, setBatchInput] = useState('');
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchProgress, setBatchProgress] = useState('');
  
  // AI Smart Excel Modal
  const [isAIModalOpen, setIsAIModalOpen] = useState(false);
  const [aiError, setAiError] = useState('');
  const [aiLoading, setAiLoading] = useState(false);

  // Inline renaming
  const [renamingId, setRenamingId] = useState(null);
  const [renameText, setRenameText] = useState('');

  // Voice recording
  const [recording, setRecording] = useState(false);
  const recognitionRef = useRef(null);

  // Chart library check
  const [chartReady, setChartReady] = useState(!!window.Chart);

  // DOM Refs
  const messageAreaRef = useRef(null);
  const textareaRef = useRef(null);
  const stopBatchTrigger = useRef(false);

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

  useEffect(() => {
    const loadStaff = async () => {
      setStaffLoading(true);
      try {
        const res = await fetch('/api/staff');
        const data = await res.json();
        setStaffList(data.staff || []);
      } catch {
        setStaffList([]);
      } finally {
        setStaffLoading(false);
      }
    };
    loadStaff();
  }, []);

  // Update sessions when selected staff member changes
  useEffect(() => {
    if (staffUid) {
      localStorage.setItem('dms_analytics_uid', staffUid);
      const list = loadSessions(staffUid);
      setSessions(list);
      
      // Auto-load most recent active session
      if (list.length > 0) {
        loadSession(list[0]);
      } else {
        startNewConversation(staffUid);
      }
    }
  }, [staffUid]);

  // Keep messages scrolled to bottom
  useEffect(() => {
    if (messageAreaRef.current) {
      messageAreaRef.current.scrollTop = messageAreaRef.current.scrollHeight;
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

  // ── Voice Transcription using browser native Web Speech ──────
  const toggleVoiceRecording = () => {
    if (recording) {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
      setRecording(false);
      return;
    }

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      alert('Speech recognition is not supported in this browser. Try Chrome, Edge or Safari.');
      return;
    }

    const rec = new SpeechRec();
    rec.continuous = false;
    rec.interimResults = false;
    rec.lang = 'en-IN'; // Hinglish & Indian English support
    
    rec.onstart = () => setRecording(true);
    rec.onend = () => setRecording(false);
    rec.onerror = () => setRecording(false);
    rec.onresult = (event) => {
      const resultText = event.results[0][0].transcript;
      if (resultText) {
        setInputText(resultText);
      }
    };
    
    recognitionRef.current = rec;
    rec.start();
  };

  // ── Chat Actions & APIs ──────────────────────────────────────
  const sendChatMessage = async (messageText) => {
    if (!messageText.trim()) return;
    if (!staffUid) {
      alert('Please select a Staff / User from the header first.');
      return;
    }

    setInputText('');
    const s = getSelectedStaff();
    
    // Add user message
    setMessages(prev => [...prev, { id: 'u-' + Date.now(), role: 'user', text: messageText }]);
    
    // Add assistant placeholder bubble
    const loadingId = 'ai-loading-' + Date.now();
    setMessages(prev => [...prev, { id: loadingId, role: 'assistant', loadingPlaceholder: true }]);
    setLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userid: staffUid,
          message: messageText,
          history: conversationContext.current.slice(-10),
          name: s?.name,
          designation: s?.designation,
          employee_code: s?.employee_code,
          username: s?.username,
          email: s?.email,
          mobile: s?.mobile
        })
      });

      const data = await response.json();
      
      const answer = data.answer || 'No response could be parsed.';
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
        hasData: sourceRows.length > 0
      } : m));

      // Append context N turns
      conversationContext.current = [
        ...conversationContext.current,
        { role: 'user', content: messageText },
        { role: 'assistant', content: answer }
      ].slice(-20);

      // Persist session history
      let activeSid = currentSessionId;
      if (!activeSid) {
        activeSid = createNewSession(staffUid);
        setCurrentSessionId(activeSid);
      }
      autoSaveSession(staffUid, activeSid, conversationContext.current);
      setSessions(loadSessions(staffUid));

    } catch (e) {
      setMessages(prev => prev.map(m => m.id === loadingId ? {
        id: 'err-' + Date.now(),
        role: 'assistant',
        html: `<p className="dms-modal-error">⚠️ Connection failure: ${e.message}</p>`
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
    lastExecutionData.current = null;
    setBatchProgress('');
    setIsDrawerOpen(false);
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
    setIsDrawerOpen(false);
  };

  const handleDeleteSession = (sid) => {
    if (!confirm('Are you sure you want to delete this chat session?')) return;
    const updated = deleteSession(staffUid, sid);
    setSessions(updated);
    if (currentSessionId === sid) {
      startNewConversation();
    }
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
  const downloadBlob = async (endpoint, payload, defaultFilename) => {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
      alert('Standard Excel export failed: ' + e.message);
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
      setIsAIModalOpen(false);
    } catch (e) {
      setAiError(e.message);
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
    messageAreaRef.current?.appendChild(metadata);
    window.print();
    setTimeout(() => metadata.remove(), 600);
  };

  // ── Batch Processing ──────────────────────────────────────────
  const executeBatch = async () => {
    if (!staffUid) {
      alert('Please select a Staff / User from the header first.');
      return;
    }
    const lines = batchInput.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length === 0) {
      alert('Please write at least one question (one per line).');
      return;
    }

    stopBatchTrigger.current = false;
    setBatchRunning(true);

    for (let index = 0; index < lines.length; index++) {
      if (stopBatchTrigger.current) break;
      setBatchProgress(`Running question ${index + 1} of ${lines.length}...`);
      
      if (index > 0) {
        setMessages(prev => [...prev, { id: 'batch-div-' + Date.now(), isBatchDivider: true, dividerText: `Question ${index + 1} of ${lines.length}` }]);
      }
      
      await sendChatMessage(lines[index]);
      // small spacer wait
      await new Promise(res => setTimeout(res, 500));
    }

    setBatchRunning(false);
    setBatchProgress(stopBatchTrigger.current ? 'Stopped batch execution.' : `Completed batch. Successfully ran ${lines.length} queries.`);
  };

  // ── Handlers ─────────────────────────────────────────────────
  const handleKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage(inputText);
    }
  };

  return (
    <div className="dms-root">
      
      {/* ── Header: Staff Selection ── */}
      <div className="dms-staff-header">
        <span className="dms-staff-label">👤 Active Role</span>
        <select
          className="dms-staff-select"
          value={staffUid}
          onChange={e => setStaffUid(e.target.value)}
          disabled={staffLoading}
        >
          <option value="">{staffLoading ? 'Loading Active staff list...' : '— Select DMS User —'}</option>
          {staffList.map(s => (
            <option key={s.userid} value={s.userid}>
              {s.name || s.username} {s.employee_code ? `[${s.employee_code}]` : ''} {s.designation ? `· ${s.designation}` : ''}
            </option>
          ))}
        </select>
        {staffUid && <span className="dms-staff-badge">ID: {staffUid}</span>}
      </div>

      {/* ── Toolbar ── */}
      <div className="dms-toolbar">
        <div className="dms-toolbar-left">
          <span className="dms-logo">📈</span>
          <div>
            <div className="dms-brand-title">DMS Analytics</div>
            <div className="dms-brand-status">
              <span className="dms-status-dot" /> Natural Language Analytics Engine
            </div>
          </div>
        </div>
        <div className="dms-toolbar-actions">
          <button 
            className={`dms-btn-tool ${isDrawerOpen ? 'active' : ''}`} 
            onClick={() => setIsDrawerOpen(prev => !prev)} 
            title="View recent chat session threads"
          >
            History List
          </button>
        </div>
      </div>

      {/* ── Main Layout Container ── */}
      <div className="dms-main-container">
        
        {/* ── History Drawer Panel ── */}
        <div className={`dms-history-drawer ${isDrawerOpen ? 'open' : ''}`}>
          <div className="dms-drawer-header">
            <span className="dms-drawer-title">Saved Discussions</span>
            <button className="dms-btn-new-chat" onClick={() => startNewConversation()}>+ New</button>
            <button className="dms-drawer-close" onClick={() => setIsDrawerOpen(false)}>&times;</button>
          </div>
          <div className="dms-drawer-list">
            {sessions.length === 0 ? (
              <div className="dms-hist-empty">
                No saved sessions for this user ID. Ask some questions to begin.
              </div>
            ) : (
              sessions.map(s => (
                <div 
                  key={s.id} 
                  className={`dms-history-item ${s.id === currentSessionId ? 'active' : ''}`}
                  onClick={() => loadSession(s)}
                >
                <div className="dms-hist-body">
                  {renamingId === s.id ? (
                    <input
                      className="dms-rename-input"
                      value={renameText}
                      onChange={e => setRenameText(e.target.value)}
                      onBlur={() => saveRenamedSession(s.id)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') saveRenamedSession(s.id);
                        if (e.key === 'Escape') setRenamingId(null);
                      }}
                      autoFocus
                      onClick={e => e.stopPropagation()}
                    />
                  ) : (
                    <div className="dms-hist-title">{s.title}</div>
                  )}
                  <div className="dms-hist-meta">
                    {formatTimeAgo(s.updated)} &bull; {s.messages.filter(m => m.role === 'user').length} queries
                  </div>
                </div>
                <div className="dms-hist-actions">
                  <button 
                    className="dms-btn-action" 
                    title="Rename" 
                    onClick={(e) => {
                      e.stopPropagation();
                      triggerRenameSession(s.id, s.title);
                    }}
                  >
                    ✏️
                  </button>
                  <button 
                    className="dms-btn-action delete" 
                    title="Delete" 
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSession(s.id);
                    }}
                  >
                    🗑️
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="dms-content-area">
        {/* ── Batch Script Box ── */}
      {isBatchOpen && (
        <div className="dms-batch-panel">
          <div className="dms-batch-header">
            <span className="dms-batch-title">Batch Processing Console</span>
            <span className="dms-batch-desc">One question per line. Automatically runs all sequentially.</span>
            <button className="dms-modal-close" style={{ color: '#818cf8' }} onClick={() => setIsBatchOpen(false)}>&times;</button>
          </div>
          <textarea
            className="dms-batch-textarea"
            placeholder="What is my secondary sales this month?&#10;Show purchase trends for last 6 months..."
            value={batchInput}
            onChange={e => setBatchInput(e.target.value)}
            disabled={batchRunning}
          />
          <div className="dms-batch-footer">
            <span className="dms-batch-progress">{batchProgress}</span>
            <div style={{ display: 'flex', gap: 6 }}>
              {batchRunning && (
                <button 
                  className="dms-btn-tool" 
                  style={{ color: '#ef4444', borderColor: 'rgba(239, 68, 68, 0.4)' }}
                  onClick={() => { stopBatchTrigger.current = true; }}
                >
                  Stop Execution
                </button>
              )}
              <button 
                className="dms-btn-batch-run" 
                onClick={executeBatch}
                disabled={batchRunning || !batchInput.trim()}
              >
                {batchRunning ? 'Running Box...' : 'Execute Script Batch'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Messages Area ── */}
      <div className="dms-messages-area" ref={messageAreaRef}>
        {messages.map((m, idx) => {
          if (m.isBatchDivider) {
            return (
              <div key={m.id || idx} className="dms-batch-divider">
                {m.dividerText}
              </div>
            );
          }

          if (m.role === 'user') {
            return (
              <div key={m.id || idx} className="dms-msg user">
                <div className="dms-msg-user-bubble">{m.text}</div>
              </div>
            );
          }

          return (
            <div key={m.id || idx} className="dms-msg ai">
              <div className="dms-ai-identity">
                <div className="dms-ai-avatar">📊</div>
                <span className="dms-ai-name">DMS Analyst</span>
              </div>
              <div className="dms-ai-bubble">
                {m.loadingPlaceholder ? (
                  <div className="dms-msg-loading">
                    <span className="dms-dot" />
                    <span className="dms-dot" />
                    <span className="dms-dot" />
                  </div>
                ) : (
                  <>
                    <div dangerouslySetInnerHTML={{ __html: m.html }} />
                    
                    {/* Render visual Chart if returned by API */}
                    {m.chartSpec && (
                      <DMSChart 
                        spec={m.chartSpec} 
                        rows={m.chartRows} 
                        chartReady={chartReady} 
                      />
                    )}

                    {/* Inline actions if response has tabular results */}
                    {m.hasData && (
                      <div className="dms-inline-actions">
                        <span className="dms-inline-label">Table Action:</span>
                        <button className="dms-inline-button" onClick={handleStandardExport}>
                          📊 Export Excel
                        </button>
                        <button className="dms-inline-button smart" onClick={() => {
                          setAiError('');
                          setIsAIModalOpen(true);
                        }}>
                          ✨ Format Spreadsheet
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Suggestion Dock & Input Row ── */}
      <div className="dms-input-dock">
        <div className="dms-suggestions-bar">
          {SUGGESTIONS.map(s => (
            <button 
              key={s} 
              className="dms-chip"
              onClick={() => sendChatMessage(s)}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="dms-input-row">
          <textarea
            ref={textareaRef}
            className="dms-text-area"
            rows={1}
            placeholder="Ask anything about secondary sales, purchases, primary..."
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={handleKeydown}
          />
          <button 
            className={`dms-btn-voice ${recording ? 'recording' : ''}`}
            onClick={toggleVoiceRecording}
            title={recording ? 'Recording voice... Click to stop.' : 'Record query via voice input'}
          >
            🎙️ {recording ? 'ON' : ''}
          </button>
          <button 
            className="dms-btn-send"
            onClick={() => sendChatMessage(inputText)}
            disabled={loading || !inputText.trim()}
          >
            ➤
          </button>
        </div>
      </div>

      </div> {/* dms-content-area */}
      </div> {/* dms-main-container */}

      {/* ── AI Smart Report Modal ── */}
      <AIReportModal
        isOpen={isAIModalOpen}
        onClose={() => setIsAIModalOpen(false)}
        onGenerate={handleSmartAIExport}
        loading={aiLoading}
        error={aiError}
      />

    </div>
  );
}

// ── Mount ─────────────────────────────────────────────────────
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(DMSChatComponent));

