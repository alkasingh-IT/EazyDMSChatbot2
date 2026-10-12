'use strict';
const API = '';
let currentView = 'chat';
let chartInstances = {};
let godModeActive = false;

function toggleGodMode() {
  godModeActive = document.getElementById('godModeToggle').checked;
  const badge = document.getElementById('godModeBadge');
  if (badge) badge.style.display = godModeActive ? 'inline-flex' : 'none';
}

function uid()     { return document.getElementById('staffSelect').value || ''; }
function loading(on) { document.getElementById('loadingOverlay').style.display = on ? 'flex' : 'none'; }

function fmtCurrency(v) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return v;
  if (n >= 1e7) return '₹' + (n/1e7).toFixed(2) + ' Cr';
  if (n >= 1e5) return '₹' + (n/1e5).toFixed(2) + ' L';
  if (n >= 1e3) return '₹' + (n/1e3).toFixed(1) + 'K';
  return '₹' + n.toLocaleString('en-IN', {maximumFractionDigits: 0});
}

function fmtNum(v) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return v;
  return n.toLocaleString('en-IN');
}

function fmtPct(v) {
  if (v == null) return '—';
  return parseFloat(v).toFixed(1) + '%';
}

function isCurrencyCol(col) { return /value|amount|sales|purchase|price|cost|revenue/i.test(col); }
function isPctCol(col) { return /pct|percent|ratio|growth/i.test(col); }
function isQtyCol(col)  { return /qty|quantity|count|invoice/i.test(col); }

function fmtCell(col, val) {
  if (val == null) return '—';
  if (isCurrencyCol(col)) return fmtCurrency(val);
  if (isPctCol(col)) return fmtPct(val);
  return val;
}

async function post(endpoint, body) {
  if (!uid()) { alert('Please select a staff member first.'); return null; }
  loading(true);
  try {
    const r = await fetch(API + endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || JSON.stringify(d));
    return d;
  } catch(e) {
    console.error(endpoint, e);
    return {error: e.message};
  } finally { loading(false); }
}

async function get(endpoint) {
  try {
    const r = await fetch(API + endpoint);
    return await r.json();
  } catch(e) { return {error: e.message}; }
}

function buildTable(containerId, rows, columns) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!rows || !rows.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div>No data found.</div>';
    return;
  }
  const cols = columns || Object.keys(rows[0]);
  const label = c => c.replace(/_/g,' ').replace(/([A-Z])/g,' $1').trim().replace(/\b\w/g,l=>l.toUpperCase());
  let html = '<div class="table-wrap"><table class="data-table"><thead><tr>';
  cols.forEach(c => { html += `<th>${label(c)}</th>`; });
  html += '</tr></thead><tbody>';
  rows.forEach(row => {
    html += '<tr>';
    cols.forEach(c => { html += `<td title="${row[c] ?? ''}">${fmtCell(c, row[c])}</td>`; });
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  el.innerHTML = html;
}

function showError(containerId, msg) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = `<div class="error-state">⚠️ ${msg}</div>`;
}

const GOLD='#2563eb', BLUE='#3b82f6', GREEN='#16a34a', ROSE='#f43f5e', AMBER='#d97706';
const PALETTE=[GOLD,GREEN,AMBER,ROSE,'#7c3aed','#0891b2','#db2777','#059669'];

const chartBase = {
  responsive: true, maintainAspectRatio: true,
  plugins: {
    legend: {labels:{color:'#4b5563',font:{size:11}}},
    tooltip: {backgroundColor:'#0f172a',borderColor:'rgba(37,99,235,.2)',borderWidth:1,titleColor:'#f1f5f9',bodyColor:'#9ca3af'}
  },
  scales: {
    x:{ticks:{color:'#6b7280',font:{size:11}},grid:{color:'rgba(37,99,235,.07)'}},
    y:{ticks:{color:'#6b7280',font:{size:11}},grid:{color:'rgba(37,99,235,.07)'}}
  }
};

function destroyChart(id) {
  if (chartInstances[id]) { try { chartInstances[id].destroy(); } catch(_){} delete chartInstances[id]; }
}

function renderBarChart(canvasId, labels, values, color, label) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  chartInstances[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: {labels, datasets:[{label:label||'Value',data:values,backgroundColor:color+'99',borderColor:color,borderWidth:1.5,borderRadius:6}]},
    options: JSON.parse(JSON.stringify(chartBase))
  });
}

function renderLineChart(canvasId, labels, values, color, label) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  chartInstances[canvasId] = new Chart(ctx, {
    type: 'line',
    data: {labels, datasets:[{label:label||'Value',data:values,borderColor:color,backgroundColor:color+'22',borderWidth:2.5,fill:true,tension:.35,pointBackgroundColor:color}]},
    options: JSON.parse(JSON.stringify(chartBase))
  });
}

function renderDoughnut(canvasId, labels, values, colors) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  chartInstances[canvasId] = new Chart(ctx, {
    type: 'doughnut',
    data: {labels, datasets:[{data:values,backgroundColor:colors||PALETTE,borderWidth:0}]},
    options: {responsive:true,plugins:{legend:{position:'right',labels:{color:'#9ca3af',font:{size:11}}},tooltip:chartBase.plugins.tooltip}}
  });
}

async function execFlag(flag, params) {
  params = params || {};
  if (godModeActive) params.god_mode = true;
  return post('/api/analytics/execute', {userid: uid(), flag, params});
}

function buildParams(view) {
  const p = {};
  const prefixMap = {
    'ss-overview':'ss-ov', 'ss-items':'ss-it', 'ss-dealers':'ss-dl',
    'ss-category':'ss-cat', 'ss-trend':'ss-tr', 'ss-distributor':'ss-dist',
    'ss-team':'ss-team', 'ss-national':'ss-nat',
    'pur-overview':'pur-ov', 'pur-category':'pur-cat', 'pur-item':'pur-item',
    'pur-pending':'pur-pen', 'pur-distributor':'pur-dist', 'pur-trend':'pur-tr',
    'pr-overview':'pr-ov', 'pr-invoices':'pr-inv', 'pr-sku':'pr-sku',
    'pr-distributor':'pr-dist', 'pr-trend':'pr-tr'
  };
  const prefix = prefixMap[view] || view;
  const from = document.getElementById(prefix+'-from');
  const to = document.getElementById(prefix+'-to');
  if (from && from.value) p.date_from = from.value;
  if (to && to.value) p.date_to = to.value;
  const limit = document.getElementById(prefix+'-limit');
  if (limit && limit.value) p.limit = parseInt(limit.value);
  const itemId = document.getElementById('pur-item-id');
  if (itemId && itemId.value) p.item_id = itemId.value;
  return p;
}

async function execMulti(view, flags) {
  const p = buildParams(view);
  const results = {};
  const all = await Promise.all(flags.map(f => execFlag(f, p)));
  flags.forEach((f, i) => { if (all[i] && !all[i].error) results[f] = all[i]; });
  return results;
}

function resetDates(view) {
  const prefixMap = {
    'ss-overview':'ss-ov', 'ss-items':'ss-it', 'ss-dealers':'ss-dl',
    'ss-category':'ss-cat', 'ss-trend':'ss-tr', 'ss-distributor':'ss-dist',
    'ss-team':'ss-team', 'ss-national':'ss-nat',
    'pur-overview':'pur-ov', 'pur-category':'pur-cat', 'pur-item':'pur-item',
    'pur-pending':'pur-pen', 'pur-distributor':'pur-dist', 'pur-trend':'pur-tr',
    'pr-overview':'pr-ov', 'pr-invoices':'pr-inv', 'pr-sku':'pr-sku',
    'pr-distributor':'pr-dist', 'pr-trend':'pr-tr'
  };
  const prefix = prefixMap[view] || view;
  ['from','to'].forEach(sfx => {
    const el = document.getElementById(prefix+'-'+sfx);
    if (el) el.value = '';
  });
}

function loadSsOverview() {
  execMulti('ss-overview', ['ss:monthly-total','ss:growth','ss:top5-items-quarter']).then(r => {
    if (r['ss:monthly-total'] && r['ss:monthly-total'].rows && r['ss:monthly-total'].rows.length) {
      const d = r['ss:monthly-total'].rows[0];
      setKpi('ssMonthSales', fmtCurrency(d.total_secondary_sales));
      setKpi('ssMonthInvoices', fmtNum(d.invoice_count) + ' invoices');
    }
    if (r['ss:growth'] && r['ss:growth'].rows && r['ss:growth'].rows.length) {
      const d = r['ss:growth'].rows[0];
      const pct = parseFloat(d.growth_pct || 0);
      setKpi('ssCurrMonth', fmtCurrency(d.current_month_sales));
      setKpi('ssLastMonth', fmtCurrency(d.last_month_sales));
      setKpi('ssGrowth', fmtPct(pct), pct >= 0 ? 'green' : 'red');
    }
    if (r['ss:top5-items-quarter'] && r['ss:top5-items-quarter'].rows && r['ss:top5-items-quarter'].rows.length) {
      const rows = r['ss:top5-items-quarter'].rows;
      renderBarChart('ssTop5Chart',
        rows.map(r => r.itemcode || r.itemid),
        rows.map(r => parseFloat(r.total_billed_value || 0)),
        GOLD, 'Billed Value (₹)');
      buildTable('ssTop5Table', rows, ['itemcode','total_billed_value']);
    }
  });
}

function loadSsItems() {
  execMulti('ss-items', ['ss:by-item-last-week']).then(r => {
    if (r['ss:by-item-last-week'] && r['ss:by-item-last-week'].rows && r['ss:by-item-last-week'].rows.length) {
      const rows = r['ss:by-item-last-week'].rows;
      renderBarChart('ssItemsChart',
        rows.map(r => r.itemcode || r.itemid),
        rows.map(r => parseFloat(r.total_billed_value || 0)),
        BLUE, 'Billed Value (₹)');
      buildTable('ssItemsTable', rows);
    } else showError('ssItemsTable', 'No data');
  });
}

function loadSsDealers() {
  execMulti('ss-dealers', ['ss:top-dealers']).then(r => {
    if (r['ss:top-dealers'] && !r['ss:top-dealers'].error && r['ss:top-dealers'].rows && r['ss:top-dealers'].rows.length) {
      const rows = r['ss:top-dealers'].rows;
      renderBarChart('ssDealersChart',
        rows.slice(0,12).map(r => (r.dealer_name || r.dealerid || '—').slice(0,15)),
        rows.slice(0,12).map(r => parseFloat(r.total_billed_value || 0)),
        GOLD, 'Sales (₹)');
      buildTable('ssDealersTable', rows);
    } else showError('ssDealersTable', r['ss:top-dealers'] && r['ss:top-dealers'].error ? r['ss:top-dealers'].error : 'No data');
  });
}

function loadSsByCategory() {
  execMulti('ss-category', ['ss:by-category']).then(r => {
    if (r['ss:by-category'] && r['ss:by-category'].rows && r['ss:by-category'].rows.length) {
      const rows = r['ss:by-category'].rows;
      renderDoughnut('ssCatChart',
        rows.slice(0,8).map(r => r.product_category || '—'),
        rows.slice(0,8).map(r => parseFloat(r.total_billed_value || 0)),
        PALETTE);
      buildTable('ssCatTable', rows);
    } else showError('ssCatTable', r['ss:by-category'] && r['ss:by-category'].error ? r['ss:by-category'].error : 'No data');
  });
}

function loadSsTrend() {
  execMulti('ss-trend', ['ss:trend-3m']).then(r => {
    if (r['ss:trend-3m'] && r['ss:trend-3m'].rows && r['ss:trend-3m'].rows.length) {
      const rows = r['ss:trend-3m'].rows;
      renderLineChart('ssTrendChart',
        rows.map(r => (r.sales_month||'').toString().slice(0,7)),
        rows.map(r => parseFloat(r.total_billed_value || 0)),
        GOLD, 'Monthly Sales (₹)');
      buildTable('ssTrendTable', rows, ['sales_month','distributorid','total_billed_value']);
    } else showError('ssTrendTable', r['ss:trend-3m'] && r['ss:trend-3m'].error ? r['ss:trend-3m'].error : 'No data');
  });
}

function loadSsGrowth() {
  execMulti('ss-growth', ['ss:growth']).then(r => {
    if (r['ss:growth'] && r['ss:growth'].rows && r['ss:growth'].rows.length) {
      const d = r['ss:growth'].rows[0];
      setKpi('gCurrMonth', fmtCurrency(d.current_month_sales));
      setKpi('gLastMonth', fmtCurrency(d.last_month_sales));
      const pct = parseFloat(d.growth_pct || 0);
      setKpi('gGrowthPct', fmtPct(pct), pct >= 0 ? 'green' : 'red');
    }
  });
}

function loadSsDistributor() {
  execMulti('ss-distributor', ['ss:by-distributor']).then(r => {
    if (r['ss:by-distributor'] && r['ss:by-distributor'].rows && r['ss:by-distributor'].rows.length) {
      const rows = r['ss:by-distributor'].rows;
      renderBarChart('ssDistChart',
        rows.slice(0,12).map(r => r.ds_code || r.distributorid),
        rows.slice(0,12).map(r => parseFloat(r.total_billed_value || 0)),
        BLUE, 'Billed Value (₹)');
      buildTable('ssDistTable', rows);
    } else showError('ssDistTable', r['ss:by-distributor'] && r['ss:by-distributor'].error ? r['ss:by-distributor'].error : 'No data');
  });
}

function loadSsTeam() {
  execMulti('ss-team', ['ss:team-by-so']).then(r => {
    if (r['ss:team-by-so'] && !r['ss:team-by-so'].error) buildTable('ssTeamTable', r['ss:team-by-so'].rows);
    else showError('ssTeamTable', r['ss:team-by-so'] && r['ss:team-by-so'].error ? r['ss:team-by-so'].error : 'No data');
  });
}

function loadSsNational() {
  execMulti('ss-national', ['ss:national']).then(r => {
    if (r['ss:national'] && r['ss:national'].rows && r['ss:national'].rows.length) {
      const d = r['ss:national'].rows[0];
      setKpi('ssNatSales', fmtCurrency(d.national_secondary_sales));
      setKpi('ssNatInvoices', fmtNum(d.invoice_count));
      setKpi('ssNatDistributors', fmtNum(d.distributor_count));
    }
  });
}

function loadPurOverview() {
  execMulti('pur-overview', ['pur:fast-total','pur:by-category','pur:this-month','pur:pending']).then(r => {
    if (r['pur:fast-total'] && r['pur:fast-total'].rows && r['pur:fast-total'].rows[0]) {
      setKpi('purTotalValue', fmtCurrency(r['pur:fast-total'].rows[0].total_purchase_value || 0));
    } else if (r['pur:this-month'] && r['pur:this-month'].rows) {
      const total = r['pur:this-month'].rows.reduce((s,row) => s + parseFloat(row.billed_value || 0), 0);
      setKpi('purTotalValue', fmtCurrency(total));
    }
    if (r['pur:this-month']) {
      setKpi('purMonthCount', (r['pur:this-month'].row_count || 0) + ' entries');
      buildTable('purMonthTable', (r['pur:this-month'].rows||[]).slice(0,20));
    }
    if (r['pur:pending']) {
      setKpi('purPendingCount', (r['pur:pending'].row_count || 0) + ' pending');
    }
    if (r['pur:by-category'] && r['pur:by-category'].rows && r['pur:by-category'].rows.length) {
      const rows = r['pur:by-category'].rows;
      renderDoughnut('purOvChart',
        rows.slice(0,8).map(r => r.item_category || '—'),
        rows.slice(0,8).map(r => parseFloat(r.total_purchase_value || 0)),
        PALETTE);
    }
  });
}

function loadPurByCategory() {
  execMulti('pur-category', ['pur:by-category']).then(r => {
    if (r['pur:by-category'] && r['pur:by-category'].rows && r['pur:by-category'].rows.length) {
      const rows = r['pur:by-category'].rows;
      renderDoughnut('purCatChart',
        rows.slice(0,8).map(r => r.item_category || '—'),
        rows.slice(0,8).map(r => parseFloat(r.total_purchase_value || 0)),
        PALETTE);
      buildTable('purCatTable', rows);
    } else showError('purCatTable', 'No data');
  });
}

function loadPurItem() {
  execMulti('pur-item', ['pur:item-history']).then(r => {
    if (r['pur:item-history'] && !r['pur:item-history'].error) buildTable('purItemTable', r['pur:item-history'].rows);
    else showError('purItemTable', r['pur:item-history'] && r['pur:item-history'].error ? r['pur:item-history'].error : 'No data');
  });
}

function loadPurPending() {
  execMulti('pur-pending', ['pur:pending']).then(r => {
    if (r['pur:pending'] && !r['pur:pending'].error) buildTable('purPendingTable', r['pur:pending'].rows);
    else showError('purPendingTable', r['pur:pending'] && r['pur:pending'].error ? r['pur:pending'].error : 'No data');
  });
}

function loadPurByDist() {
  execMulti('pur-distributor', ['pur:by-distributor']).then(r => {
    if (r['pur:by-distributor'] && r['pur:by-distributor'].rows && r['pur:by-distributor'].rows.length) {
      const rows = r['pur:by-distributor'].rows;
      renderBarChart('purDistChart',
        rows.slice(0,12).map(r => r.ds_code || r.distributorid),
        rows.slice(0,12).map(r => parseFloat(r.total_purchase_value || 0)),
        AMBER, 'Purchase Value (₹)');
      buildTable('purDistTable', rows);
    } else showError('purDistTable', r['pur:by-distributor'] && r['pur:by-distributor'].error ? r['pur:by-distributor'].error : 'No data');
  });
}

function loadPurTrend() {
  execMulti('pur-trend', ['pur:trend-6m']).then(r => {
    if (r['pur:trend-6m'] && r['pur:trend-6m'].rows && r['pur:trend-6m'].rows.length) {
      const rows = r['pur:trend-6m'].rows;
      renderLineChart('purTrendChart',
        rows.map(r => (r.purchase_month||'').toString().slice(0,7)),
        rows.map(r => parseFloat(r.total_purchase_value || 0)),
        AMBER, 'Purchase Value (₹)');
      buildTable('purTrendTable', rows);
    } else showError('purTrendTable', r['pur:trend-6m'] && r['pur:trend-6m'].error ? r['pur:trend-6m'].error : 'No data');
  });
}

function loadPurRecon() {
  execMulti('pur-recon', ['pur:reconciliation']).then(r => {
    if (r['pur:reconciliation'] && !r['pur:reconciliation'].error) buildTable('purReconTable', r['pur:reconciliation'].rows);
    else showError('purReconTable', r['pur:reconciliation'] && r['pur:reconciliation'].error ? r['pur:reconciliation'].error : 'No data');
  });
}

function loadPrOverview() {
  execMulti('pr-overview', ['pr:region-total','pr:vs-secondary']).then(r => {
    if (r['pr:region-total'] && r['pr:region-total'].rows && r['pr:region-total'].rows.length) {
      const d = r['pr:region-total'].rows[0];
      setKpi('prMonthSales', d.total_primary_sales ? fmtCurrency(d.total_primary_sales) : '₹0');
      setKpi('prMonthInvoices', (d.invoice_count || 0) + ' invoices');
    }
    if (r['pr:vs-secondary'] && r['pr:vs-secondary'].rows && r['pr:vs-secondary'].rows.length) {
      const d = r['pr:vs-secondary'].rows[0];
      setKpi('prVsPrimary', d.primary_sales_value ? fmtCurrency(d.primary_sales_value) : '₹0');
      setKpi('prVsSecondary', d.secondary_sales_value ? fmtCurrency(d.secondary_sales_value) : '₹0');
      renderBarChart('prVsChart',
        ['Primary (Receipts)', 'Secondary (Sales)'],
        [parseFloat(d.primary_sales_value||0), parseFloat(d.secondary_sales_value||0)],
        BLUE, '₹ Value');
    }
  });
}

function loadPrInvoices() {
  execMulti('pr-invoices', ['pr:fast-total','pr:last-30d']).then(r => {
    if (r['pr:fast-total'] && r['pr:fast-total'].rows && r['pr:fast-total'].rows[0]) {
      const d = r['pr:fast-total'].rows[0];
      setKpi('prInvTotal', fmtCurrency(d.total_primary_sales || 0));
      setKpi('prInvCount', fmtNum(r['pr:last-30d'] && r['pr:last-30d'].row_count || (r['pr:last-30d'] && r['pr:last-30d'].rows ? r['pr:last-30d'].rows.length : 0)));
    }
    if (r['pr:last-30d'] && !r['pr:last-30d'].error) {
      const rows = r['pr:last-30d'].rows;
      buildTable('prInvoicesTable', rows, ['invoiceno','invoicedate','partyid','net_amount','gross_amount','discount_amount','isauthorized']);
      const dayMap = {};
      let total = 0;
      rows.forEach(row => {
        const d = (row.invoicedate||'').slice(0,10);
        if (!d) return;
        dayMap[d] = (dayMap[d]||0) + parseFloat(row.net_amount||0);
        total += parseFloat(row.net_amount||0);
      });
      const sorted = Object.keys(dayMap).sort();
      renderLineChart('prInvChart',
        sorted.slice(-30),
        sorted.slice(-30).map(d => dayMap[d]),
        BLUE, 'Daily Value (₹)');
      if (sorted.length <= 1) document.querySelector('#prInvChart').style.display = 'none';
    }
    if (!r['pr:fast-total'] || !r['pr:fast-total'].rows) {
      setKpi('prInvTotal', '₹0');
      setKpi('prInvCount', '0');
    }
  });
}

function loadPrBySku() {
  execMulti('pr-sku', ['pr:by-sku']).then(r => {
    if (r['pr:by-sku'] && r['pr:by-sku'].rows && r['pr:by-sku'].rows.length) {
      const rows = r['pr:by-sku'].rows;
      renderBarChart('prSkuChart',
        rows.slice(0,12).map(r => r.itemcode || r.itemid),
        rows.slice(0,12).map(r => parseFloat(r.total_value || 0)),
        GREEN, 'Value (₹)');
      buildTable('prSkuTable', rows);
    } else showError('prSkuTable', r['pr:by-sku'] && r['pr:by-sku'].error ? r['pr:by-sku'].error : 'No data');
  });
}

function loadPrByDist() {
  execMulti('pr-distributor', ['pr:by-distributor']).then(r => {
    if (r['pr:by-distributor'] && r['pr:by-distributor'].rows && r['pr:by-distributor'].rows.length) {
      const rows = r['pr:by-distributor'].rows;
      renderBarChart('prDistChart',
        rows.slice(0,12).map(r => r.distributorid),
        rows.slice(0,12).map(r => parseFloat(r.total_primary_sales || 0)),
        BLUE, 'Primary Sales (₹)');
      buildTable('prDistTable', rows);
    } else showError('prDistTable', r['pr:by-distributor'] && r['pr:by-distributor'].error ? r['pr:by-distributor'].error : 'No data');
  });
}

function loadPrRatio() {
  execMulti('pr-ratio', ['pr:ratio']).then(r => {
    if (r['pr:ratio'] && !r['pr:ratio'].error) buildTable('prRatioTable', r['pr:ratio'].rows);
    else showError('prRatioTable', r['pr:ratio'] && r['pr:ratio'].error ? r['pr:ratio'].error : 'No data');
  });
}

function loadPrTrend() {
  execMulti('pr-trend', ['pr:trend-6m']).then(r => {
    if (r['pr:trend-6m'] && r['pr:trend-6m'].rows && r['pr:trend-6m'].rows.length) {
      const rows = r['pr:trend-6m'].rows;
      renderLineChart('prTrendChart',
        rows.map(r => (r.invoice_month||'').toString().slice(0,7)),
        rows.map(r => parseFloat(r.total_primary_sales || 0)),
        BLUE, 'Primary Sales (₹)');
      buildTable('prTrendTable', rows);
    } else showError('prTrendTable', r['pr:trend-6m'] && r['pr:trend-6m'].error ? r['pr:trend-6m'].error : 'No data');
  });
}

function loadPrNational() {
  execMulti('pr-national', ['pr:region-total','pr:national']).then(r => {
    if (r['pr:region-total'] && r['pr:region-total'].rows && r['pr:region-total'].rows.length) {
      const d = r['pr:region-total'].rows[0];
      setKpi('prNatSales', d.total_primary_sales ? fmtCurrency(d.total_primary_sales) : '₹0');
      setKpi('prNatInvoices', d.invoice_count ? fmtNum(d.invoice_count) : '0');
      setKpi('prNatDistributors', d.distributor_count ? fmtNum(d.distributor_count) : '0');
    } else {
      setKpi('prNatSales', '₹0');
      setKpi('prNatInvoices', '0');
      setKpi('prNatDistributors', '0');
    }
    if (r['pr:national'] && !r['pr:national'].error && r['pr:national'].rows && r['pr:national'].rows.length) {
      buildTable('prNatTable', r['pr:national'].rows);
    }
  });
}

function setKpi(id, value, badgeClass) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
  if (badgeClass) {
    const badge = el.closest('.kpi-card') && el.closest('.kpi-card').querySelector('.kpi-badge');
    if (badge) { badge.className = 'kpi-badge ' + badgeClass; badge.textContent = value; }
  }
}

function loadCombined() {
  execMulti('combined', ['combined:overview','combined:cross-compare']).then(r => {
    if (r['combined:overview'] && r['combined:overview'].rows && r['combined:overview'].rows.length) {
      const d = r['combined:overview'].rows[0];
      setKpi('cbSsSales', fmtCurrency(d.ss_sales));
      setKpi('cbSsInvoices', fmtNum(d.ss_invoices) + ' invoices');
      setKpi('cbSsGrowth', fmtPct(d.ss_growth));
      setKpi('cbPurEntries', fmtNum(d.purchase_entries));
      setKpi('cbPurPending', fmtNum(d.purchase_pending) + ' pending');
      setKpi('cbPrSales', fmtCurrency(d.pr_sales));
      setKpi('cbPrInvoices', fmtNum(d.pr_invoices) + ' invoices');
      const label = document.querySelector('#view-combined .chart-header .chart-title');
      if (label) label.textContent = 'SS vs Purchases vs Primary — ' + (d.month_label || 'This Month');
      const labels = ['Secondary Sales','Purchases','Primary Sales'];
      const vals = [parseFloat(d.ss_sales||0), parseFloat(d.purchase_entries||0), parseFloat(d.pr_sales||0)];
      renderBarChart('cbCompareChart', labels, vals, GOLD, 'Value');
    }
    if (r['combined:cross-compare'] && r['combined:cross-compare'].rows) {
      buildTable('cbCrossTable', r['combined:cross-compare'].rows);
    }
  });
}

function loadGroup() {
  const userIds = document.getElementById('groupUserIds').value.trim();
  if (!userIds) { showError('groupTable', 'Enter at least one user ID.'); return; }
  const flag = document.getElementById('groupFlagSelect').value;
  if (!flag) { showError('groupTable', 'Select a flag.'); return; }
  const ids = userIds.split(',').map(s => s.trim()).filter(Boolean).map(Number);
  document.getElementById('groupUserCount').textContent = ids.length;
  document.getElementById('groupFlagLabel').textContent = flag;
  post('/api/analytics/group', {user_ids: ids, flag, params: {god_mode: godModeActive}}).then(r => {
    if (r && r.results) {
      const all = [];
      for (const uidKey in r.results) {
        const res = r.results[uidKey];
        if (res && res.rows) {
          res.rows.forEach(row => {
            row._userid = uidKey.replace('_','');
            all.push(row);
          });
        }
      }
      document.querySelector('#view-group .kpi-sub').textContent = 'Comparing across ' + ids.length + ' users · ' + all.length + ' total rows';
      if (all.length) buildTable('groupTable', all);
      else showError('groupTable', 'No data returned for the selected flag and users.');
    }
  });
}

function loadCustomQuery() {
  const sql = document.getElementById('customSqlInput').value.trim();
  if (!sql) { showError('customQueryTable', 'Enter a SQL query.'); return; }
  const body = {userid: uid() || '0', sql, god_mode: document.getElementById('customGodMode').checked};
  if (!uid()) body._admin = true;
  loading(true);
  fetch('/api/analytics/custom', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
    .then(r => r.json().catch(() => ({error: 'Invalid response from server'})))
    .then(r => {
    const meta = document.getElementById('customQueryMeta');
    if (r && r.rows) {
      meta.style.display = 'flex';
      document.getElementById('customQueryInfo').textContent = r.rows.length + ' rows';
      buildTable('customQueryTable', r.rows, r.columns);
    } else if (r && r.error) {
      meta.style.display = 'none';
      showError('customQueryTable', r.error);
    } else {
      meta.style.display = 'none';
      showError('customQueryTable', 'No results.');
    }
    loading(false);
  }).catch(e => { loading(false); showError('customQueryTable', e.message); });
}

const VIEW_META = {
  'chat':           {title:'AI Assistant',                  sub:'Ask anything about DMS data in plain English',          loader: null},
  'combined':       {title:'Combined Dashboard',            sub:'SS + Purchases + Primary KPIs side by side',            loader: loadCombined},
  'group':          {title:'Group Analytics',               sub:'Compare the same flag across multiple users',           loader: loadGroup},
  'custom-query':   {title:'Custom SQL Query',              sub:'Run free-form SELECT queries',                          loader: loadCustomQuery},
  'ss-overview':    {title:'Secondary Sales Overview',      sub:'Monthly totals, growth, and top items',                loader: loadSsOverview},
  'ss-items':       {title:'Items by Secondary Sales',      sub:'Item-wise secondary sales breakdown',                  loader: loadSsItems},
  'ss-dealers':     {title:'Top Dealers',                   sub:'Dealers ranked by secondary sales',                    loader: loadSsDealers},
  'ss-category':    {title:'Sales by Category',             sub:'Product category breakdown',                           loader: loadSsByCategory},
  'ss-trend':       {title:'Sales Trend (3 Months)',        sub:'Month-over-month secondary sales trajectory',           loader: loadSsTrend},
  'ss-growth':      {title:'Sales Growth (MoM)',            sub:'This month vs last month comparison',                  loader: loadSsGrowth},
  'ss-distributor': {title:'Distributor-Wise Sales',        sub:'Secondary sales per distributor',                      loader: loadSsDistributor},
  'ss-team':        {title:'Team Performance by SO',        sub:'Sales officer wise secondary sales',                   loader: loadSsTeam},
  'ss-national':    {title:'National Secondary Sales',      sub:'Total national secondary sales [NSM]',                 loader: loadSsNational},
  'pur-overview':   {title:'Purchases Overview',            sub:'Purchase entries, pending items, and totals',          loader: loadPurOverview},
  'pur-category':   {title:'Purchases by Category',         sub:'Item category breakdown',                              loader: loadPurByCategory},
  'pur-item':       {title:'Purchase Item History',         sub:'Purchase history for a specific item',                 loader: loadPurItem},
  'pur-pending':    {title:'Pending Purchases',             sub:'Unmatched or unapproved purchase entries',             loader: loadPurPending},
  'pur-distributor':{title:'Purchases by Distributor',      sub:'Area-wise distributor purchase volumes',               loader: loadPurByDist},
  'pur-trend':      {title:'Purchase Trend (6 Months)',     sub:'Monthly purchase value trajectory',                    loader: loadPurTrend},
  'pur-recon':      {title:'Purchase Reconciliation',       sub:'Tally purchases vs DMS primary sales variance',        loader: loadPurRecon},
  'pr-overview':    {title:'Primary Sales Overview',        sub:'Company receipts vs secondary offtake',                loader: loadPrOverview},
  'pr-invoices':    {title:'Primary Invoices',              sub:'Last 30 days primary invoices',                        loader: loadPrInvoices},
  'pr-sku':         {title:'Primary Sales by SKU',          sub:'Item/SKU breakdown of primary inflows',                loader: loadPrBySku},
  'pr-distributor': {title:'Primary by Distributor',        sub:'All distributors ranked by primary sales',             loader: loadPrByDist},
  'pr-ratio':       {title:'Primary vs Secondary Ratio',    sub:'Offtake ratio: how much secondary vs primary received',loader: loadPrRatio},
  'pr-trend':       {title:'Primary Sales Trend (6M)',      sub:'Monthly primary sales trend',                          loader: loadPrTrend},
  'pr-national':    {title:'National Primary Sales',        sub:'National primary sales [NSM]',                         loader: loadPrNational},
};

function switchView(view) {
  if (!VIEW_META[view]) return;
  currentView = view;
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const active = document.querySelector(`[data-view="${view}"]`);
  if (active) active.classList.add('active');
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  const section = document.getElementById('view-' + view);
  if (section) section.classList.add('active');
  const meta = VIEW_META[view];
  document.getElementById('viewTitle').textContent = meta.title;
  document.getElementById('viewSubtitle').textContent = meta.sub;
}

function loadCurrentView() {
  const meta = VIEW_META[currentView];
  if (meta && meta.loader) meta.loader();
}

let staffMap = {};

function updateStaffCard(selectedUid) {
  const card = document.getElementById('staffInfoCard');
  if (!selectedUid || !staffMap[selectedUid]) { card.style.display = 'none'; return; }
  const s = staffMap[selectedUid];
  document.getElementById('siName').textContent    = s.name || s.userid;
  document.getElementById('siDesig').textContent   = s.designation || '';
  document.getElementById('siUsername').textContent = s.username   ? '🔑 ' + s.username    : '';
  document.getElementById('siEmpCode').textContent  = s.employee_code ? '🪪 ' + s.employee_code : '';
  document.getElementById('siEmail').textContent    = s.email    ? '✉️ ' + s.email    : '';
  document.getElementById('siMobile').textContent   = s.mobile   ? '📞 ' + s.mobile   : '';
  card.style.display = 'block';
}

async function fetchStaff() {
  const sel = document.getElementById('staffSelect');
  sel.innerHTML = '<option value="">Loading staff...</option>';
  const data = await get('/api/staff');
  if (!data || data.error || !data.staff || !data.staff.length) {
    sel.innerHTML = '<option value="">No staff found</option>';
    return;
  }
  sel.innerHTML = '<option value="">— Select Staff —</option>';
  staffMap = {};
  data.staff.forEach(s => {
    staffMap[s.userid] = s;
    const opt = document.createElement('option');
    opt.value = s.userid;
    const name = (s.name || '').trim() || s.userid;
    const uname = (s.username && s.username !== s.name) ? ` [${s.username}]` : '';
    const code = s.employee_code ? ` (${s.employee_code})` : '';
    const desig = s.designation ? ` · ${s.designation}` : '';
    opt.textContent = name + uname + code + desig;
    if (s.email || s.mobile) { opt.title = `${s.email || ''} ${s.mobile || ''}`.trim(); }
    sel.appendChild(opt);
  });
  const integrationUid = localStorage.getItem('dms_analytics_uid');
  const savedUid       = localStorage.getItem('dms_staff_uid');
  const autoUid        = integrationUid || savedUid;
  if (autoUid && data.staff.find(s => s.userid === autoUid)) {
    sel.value = autoUid;
    updateStaffCard(autoUid);
    if (uid()) { loadCurrentView(); initSessionsForUid(autoUid); }
  }
}

const _SESS_PFX = 'dmsSessions_';
function _sessKey(u)  { return _SESS_PFX + (u || 'anon'); }
function _loadSess(u) { try { return JSON.parse(localStorage.getItem(_sessKey(u)) || '[]'); } catch(e) { return []; } }
function _saveSess(u, arr) { try { localStorage.setItem(_sessKey(u), JSON.stringify(arr.slice(0,30))); } catch(e) {} }
function _newSess(u) {
  const id = String(Date.now());
  const arr = _loadSess(u);
  arr.unshift({id, title:'New Chat', createdAt:new Date().toISOString(), updatedAt:new Date().toISOString(), messages:[]});
  _saveSess(u, arr);
  return id;
}
function _autoSave(u, sid, msgs) {
  const arr = _loadSess(u);
  const idx = arr.findIndex(s => s.id === sid);
  if (idx === -1) return;
  arr[idx].messages = msgs.slice();
  arr[idx].updatedAt = new Date().toISOString();
  if (arr[idx].title === 'New Chat') {
    const first = msgs.find(m => m.role === 'user');
    if (first) arr[idx].title = first.content.slice(0,48) + (first.content.length > 48 ? '…' : '');
  }
  _saveSess(u, arr);
}
function _deleteSess(u, sid) { _saveSess(u, _loadSess(u).filter(s => s.id !== sid)); }
function _renameSess(u, sid, title) {
  const arr = _loadSess(u);
  const idx = arr.findIndex(s => s.id === sid);
  if (idx !== -1) { arr[idx].title = title.trim() || 'Untitled'; _saveSess(u, arr); }
}
function _fmtAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
  return new Date(iso).toLocaleDateString('en-IN', {day:'2-digit', month:'short'});
}
function _esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

let conversationHistory = [];
let currentSessionId    = null;
let lastChatExec        = null;
const MAX_TURNS = 10;

const _WELCOME = () =>
  '<div class="chat-message ai">'+
  '<div class="chat-ai-header"><div class="chat-ai-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><span class="chat-ai-name">DMS AI</span></div>'+
  '<div class="chat-ai-body">👋 Welcome to <strong>DMS AI</strong>! Ask me about <strong>secondary sales</strong>, <strong>purchases</strong>, or <strong>primary sales</strong> data in plain English.</div></div>';

function parseMarkdownTable(text) {
  var lines = text.split('\n');
  var result = [];
  var i = 0;
  while (i < lines.length) {
    var line = lines[i];
    if (/^\s*\|/.test(line)) {
      var tableLines = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { tableLines.push(lines[i]); i++; }
      if (tableLines.length >= 2) {
        var headerCells = tableLines[0].split('|').filter(function(c, idx, arr) { return idx > 0 && idx < arr.length - 1; }).map(function(c) { return c.trim(); });
        var isSep = /^[\s|:\-]+$/.test(tableLines[1]);
        var bodyStart = isSep ? 2 : 1;
        var html = '<div class="chat-md-table-wrap"><table class="chat-md-table"><thead><tr>';
        headerCells.forEach(function(h) { html += '<th>' + h + '</th>'; });
        html += '</tr></thead><tbody>';
        for (var r = bodyStart; r < tableLines.length; r++) {
          var cells = tableLines[r].split('|').filter(function(c, idx, arr) { return idx > 0 && idx < arr.length - 1; });
          html += '<tr>';
          cells.forEach(function(c) { html += '<td>' + c.trim() + '</td>'; });
          html += '</tr>';
        }
        html += '</tbody></table></div>';
        result.push(html);
      } else { result.push(tableLines.join('\n')); }
    } else { result.push(lines[i]); i++; }
  }
  return result.join('\n');
}

function renderAnalyticalAnswer(text) {
  if (!text) return '<em>No response</em>';
  var processed = parseMarkdownTable(text);
  var html = processed
    .replace(/^## (.+)$/gm, '<h4 class="chat-section-head">$1</h4>')
    .replace(/^### (.+)$/gm, '<h5 class="chat-section-subhead">$1</h5>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^[-\u2022] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, function(m) { return '<ul class="chat-bullets">' + m + '</ul>'; })
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br>');
  if (html.charAt(0) !== '<') html = '<p>' + html + '</p>';
  return '<div class="chat-analytical">' + html + '</div>';
}

var CHAT_CHART_COLORS = ['#2563eb','#3b82f6','#16a34a','#d97706','#dc2626','#7c3aed','#db2777','#0d9488','#ea580c','#4f46e5','#65a30d','#0891b2'];

var CHART_TYPE_ICONS = {
  bar:  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="9"/><rect x="10" y="7" width="4" height="14"/><rect x="17" y="3" width="4" height="18"/></svg>',
  line: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
  pie:  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>'
};

function buildChartInstance(canvas, type, labels, values, yLabel) {
  if (type === 'pie') {
    return new Chart(canvas, {
      type: 'doughnut',
      data: { labels: labels, datasets: [{ data: values, backgroundColor: CHAT_CHART_COLORS.slice(0, labels.length), borderWidth: 0 }] },
      options: {
        responsive: true,
        plugins: { legend: { position: 'right', labels: { color: '#334155', font: { size: 11 }, padding: 12 } }, tooltip: { backgroundColor: '#1e3a8a', borderColor: 'rgba(37,99,235,.3)', borderWidth: 1, titleColor: '#fff', bodyColor: '#bfdbfe' } }
      }
    });
  }
  var isLine = type === 'line';
  return new Chart(canvas, {
    type: type,
    data: {
      labels: labels,
      datasets: [{
        label: yLabel, data: values,
        backgroundColor: isLine ? 'rgba(37,99,235,0.12)' : 'rgba(37,99,235,0.75)',
        borderColor: '#2563eb', borderWidth: isLine ? 2.5 : 1.5,
        borderRadius: type === 'bar' ? 6 : 0, fill: isLine, tension: 0.35, pointBackgroundColor: '#2563eb'
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#334155', font: { size: 11 } } }, tooltip: { backgroundColor: '#1e3a8a', borderColor: 'rgba(37,99,235,.3)', borderWidth: 1, titleColor: '#fff', bodyColor: '#bfdbfe' } },
      scales: { x: { ticks: { color: '#64748b', font: { size: 10 }, maxRotation: 45, minRotation: 20 }, grid: { color: 'rgba(37,99,235,.07)' } }, y: { ticks: { color: '#64748b', font: { size: 11 } }, grid: { color: 'rgba(37,99,235,.07)' } } }
    }
  });
}

function renderChatChart(chatEl, chartSpec, rows) {
  if (!chartSpec || !chartSpec.chart_type || !rows.length) return;
  var availableTypes = chartSpec.available_types || [chartSpec.chart_type];
  var currentType = chartSpec.chart_type;
  var yLabel = (chartSpec.y || '').replace(/([A-Z])/g, ' $1').trim();
  var labels = rows.map(function(r) { var v = r[chartSpec.x]; return v != null ? String(v) : ''; });
  var values = rows.map(function(r) { return parseFloat(r[chartSpec.y] || 0); });
  if (labels.length > 30) { labels = labels.slice(0, 30); values = values.slice(0, 30); }
  var wrap = document.createElement('div');
  wrap.className = 'chat-chart-container';
  if (availableTypes.length > 1) {
    var toggleBar = document.createElement('div');
    toggleBar.className = 'chat-chart-toggle';
    var lbl = document.createElement('span');
    lbl.className = 'chart-type-toggle-label';
    lbl.textContent = 'View as';
    toggleBar.appendChild(lbl);
    availableTypes.forEach(function(t) {
      var btn = document.createElement('button');
      btn.className = 'chart-type-btn' + (t === currentType ? ' active' : '');
      btn.innerHTML = (CHART_TYPE_ICONS[t] || '') + ' ' + t.charAt(0).toUpperCase() + t.slice(1);
      btn.dataset.type = t;
      toggleBar.appendChild(btn);
    });
    wrap.appendChild(toggleBar);
  }
  var canvas = document.createElement('canvas');
  canvas.id = 'chatChart_' + Date.now();
  wrap.appendChild(canvas);
  chatEl.appendChild(wrap);
  var chartInst = null;
  try { chartInst = buildChartInstance(canvas, currentType, labels, values, yLabel); }
  catch(e) { console.error('Chart render error:', e); wrap.innerHTML = '<div class="chat-error">Chart rendering failed</div>'; return; }
  if (availableTypes.length > 1) {
    wrap.querySelector('.chat-chart-toggle').addEventListener('click', function(e) {
      var btn = e.target.closest('.chart-type-btn');
      if (!btn) return;
      var newType = btn.dataset.type;
      if (newType === currentType) return;
      currentType = newType;
      wrap.querySelectorAll('.chart-type-btn').forEach(function(b) { b.classList.toggle('active', b.dataset.type === newType); });
      if (chartInst) { try { chartInst.destroy(); } catch(_){} }
      try { chartInst = buildChartInstance(canvas, newType, labels, values, yLabel); } catch(e) {}
    });
  }
  chatEl.scrollTop = chatEl.scrollHeight;
}

function renderHistPanel() {
  const staffUid = uid();
  const sessions = _loadSess(staffUid);
  const list  = document.getElementById('chatHistList');
  const badge = document.getElementById('chatHistUidBadge');
  if (badge) badge.textContent = staffUid ? ('UID: ' + staffUid) : '';
  if (!sessions.length) { list.innerHTML = '<div class="chat-hist-empty">No saved sessions yet.<br>Start a conversation to begin.</div>'; return; }
  list.innerHTML = '';
  sessions.forEach(s => {
    const item = document.createElement('div');
    item.className = 'chat-hist-item' + (s.id === currentSessionId ? ' active' : '');
    const cnt = s.messages.filter(m => m.role === 'user').length;
    item.innerHTML =
      '<div class="chat-hist-item-body">'+
        '<div class="chat-hist-item-title">'+_esc(s.title)+'</div>'+
        '<div class="chat-hist-item-meta">'+_fmtAgo(s.updatedAt)+' &bull; '+cnt+' msg'+(cnt!==1?'s':'')+'</div>'+
      '</div>'+
      '<div class="chat-hist-item-actions">'+
        '<button class="chat-hist-act-btn ren-btn" title="Rename"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>'+
        '<button class="chat-hist-act-btn del-btn" title="Delete"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg></button>'+
      '</div>';
    item.addEventListener('click', e => {
      if (e.target.closest('.chat-hist-item-actions')) return;
      loadSessionIntoChat(staffUid, s.id);
      document.getElementById('chatHistPanel').classList.remove('open');
    });
    item.querySelector('.ren-btn').addEventListener('click', e => {
      e.stopPropagation();
      const titleEl = item.querySelector('.chat-hist-item-title');
      titleEl.innerHTML = '<input class="chat-hist-rename-input" value="'+_esc(s.title)+'" maxlength="60">';
      const inp = titleEl.querySelector('input');
      inp.focus(); inp.select();
      const commit = () => { const v = inp.value.trim() || s.title; _renameSess(staffUid, s.id, v); s.title=v; renderHistPanel(); };
      inp.addEventListener('blur', commit);
      inp.addEventListener('keydown', ev => { if(ev.key==='Enter') inp.blur(); if(ev.key==='Escape') renderHistPanel(); });
    });
    item.querySelector('.del-btn').addEventListener('click', e => {
      e.stopPropagation();
      if (!confirm('Delete "'+s.title+'"?')) return;
      _deleteSess(staffUid, s.id);
      if (currentSessionId === s.id) startNewSession();
      else renderHistPanel();
    });
    list.appendChild(item);
  });
}

function loadSessionIntoChat(staffUid, sid) {
  const session = _loadSess(staffUid).find(s => s.id === sid);
  if (!session) return;
  currentSessionId    = sid;
  conversationHistory = session.messages.slice();
  lastChatExec        = null;
  const chatEl = document.getElementById('chatHistory');
  chatEl.innerHTML = _WELCOME();
  session.messages.forEach(m => {
    const div = document.createElement('div');
    if (m.role === 'user') { div.className = 'chat-message user'; div.textContent = m.content; }
    else {
      div.className = 'chat-message ai';
      div.innerHTML = '<div class="chat-ai-header"><div class="chat-ai-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><span class="chat-ai-name">DMS AI</span></div><div class="chat-ai-body">'+renderAnalyticalAnswer(m.content)+'</div>';
    }
    chatEl.appendChild(div);
  });
  chatEl.scrollTop = chatEl.scrollHeight;
  renderHistPanel();
}

function startNewSession() {
  const staffUid = uid();
  if (!staffUid) return;
  currentSessionId    = _newSess(staffUid);
  conversationHistory = [];
  lastChatExec        = null;
  const chatEl = document.getElementById('chatHistory');
  chatEl.innerHTML = _WELCOME();
  renderHistPanel();
}

function initSessionsForUid(staffUid) {
  if (!staffUid) { currentSessionId = null; return; }
  const sessions = _loadSess(staffUid);
  if (sessions.length) loadSessionIntoChat(staffUid, sessions[0].id);
  else startNewSession();
}

async function downloadXlsx(url, payload) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  if (!r.ok) { let d = null; try { d = await r.json(); } catch(_){} throw new Error((d && (d.detail || d.error)) || ('Export failed: HTTP '+r.status)); }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = payload.filename || 'export.xlsx';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function sendSuggestion(text) {
  document.getElementById('chatInput').value = text;
  handleChat();
}

async function handleChat() {
  const chatInput = document.getElementById('chatInput');
  const chatEl    = document.getElementById('chatHistory');
  const question  = (chatInput.value || '').trim();
  if (!question) return;
  if (!uid()) { alert('Please select a staff member first.'); return; }
  if (!currentSessionId) currentSessionId = _newSess(uid());
  const userDiv = document.createElement('div');
  userDiv.className = 'chat-message user';
  userDiv.textContent = question;
  chatEl.appendChild(userDiv);
  chatInput.value = '';
  chatEl.scrollTop = chatEl.scrollHeight;
  const aiDiv = document.createElement('div');
  aiDiv.className = 'chat-message ai';
  aiDiv.innerHTML = '<div class="chat-ai-header"><div class="chat-ai-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><span class="chat-ai-name">DMS AI</span></div><div class="chat-ai-body"><span class="chat-loading" id="chat-loading-msg">Analysing<span class="dot-anim"></span></span></div>';
  chatEl.appendChild(aiDiv);
  chatEl.scrollTop = chatEl.scrollHeight;
  try {
    const loadEl = document.getElementById('chat-loading-msg');
    const loadMsgs = ['Fetching data','Still running...','This may take a while...','Almost done...'];
    let loadIdx = 0;
    const loadTimer = setInterval(() => {
      if (loadIdx < loadMsgs.length && loadEl) {
        loadEl.innerHTML = loadMsgs[loadIdx] + '<span class="dot-anim"></span>';
        loadIdx++;
      }
    }, 25000);
    const staff = staffMap[uid()] || {};
    const resp  = await fetch(API + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        userid: uid(), message: question, history: conversationHistory.slice(-MAX_TURNS * 2),
        name: staff.name || '', designation: staff.designation || '',
        employee_code: staff.employee_code || '', username: staff.username || '',
        email: staff.email || '', mobile: staff.mobile || ''
      })
    });
    clearInterval(loadTimer);
    const data   = await resp.json();
    const answer = (data && data.answer) ? data.answer : '⚠️ No response.';
    aiDiv.innerHTML = '<div class="chat-ai-header"><div class="chat-ai-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><span class="chat-ai-name">DMS AI</span></div><div class="chat-ai-body">'+renderAnalyticalAnswer(answer)+'</div>';
    const execData = (data && data.columns && data.rows && data.rows.length)
      ? {columns: data.columns, rows: data.rows, row_count: data.row_count || data.rows.length}
      : null;
    if (execData) {
      lastChatExec = execData;
      const actDiv = document.createElement('div');
      actDiv.className = 'chat-message ai';
      (function(ex) {
        const hidden = ['_flag','_desc','_flag_prefix'];
        const cols = (ex.columns || Object.keys(ex.rows[0] || {})).filter(c => !hidden.includes(c));
        const label = c => c.replace(/_/g,' ').replace(/([A-Z])/g,' $1').trim().replace(/\b\w/g,l=>l.toUpperCase());
        let tableHtml = '';
        if (ex.rows && ex.rows.length) {
          tableHtml = '<div class="chat-data-table-wrap"><table class="chat-data-table"><thead><tr>';
          cols.forEach(c => { tableHtml += `<th>${label(c)}</th>`; });
          tableHtml += '</tr></thead><tbody>';
          ex.rows.forEach(row => {
            tableHtml += '<tr>';
            cols.forEach(c => { const v = row[c]; tableHtml += `<td>${v != null ? v : ''}</td>`; });
            tableHtml += '</tr>';
          });
          tableHtml += '</tbody></table></div>';
        }
        actDiv.innerHTML = tableHtml +
          '<div class="chat-inline-actions"><span class="chat-inline-label">'+ex.row_count+' rows</span>'+
          '<button class="chat-inline-btn chat-inline-export">'+
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg> Export Excel'+
          '</button>'+
          '<button class="chat-inline-btn chat-inline-ai">'+
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> AI Report'+
          '</button></div>';
        actDiv.querySelector('.chat-inline-export').addEventListener('click', async () => {
          try { await downloadXlsx('/api/export/xlsx', {columns:ex.columns, rows:ex.rows, filename:'dms_export_'+Date.now()+'.xlsx'}); }
          catch(e) { alert('Export failed: '+e.message); }
        });
        actDiv.querySelector('.chat-inline-ai').addEventListener('click', () => { lastChatExec = ex; openAiModal(); });
      })(execData);
      chatEl.appendChild(actDiv);
    }
    if (data && data.chart_spec && data.chart_spec.chart_type) {
      const cs   = data.chart_spec;
      const rows = cs.rows || (data.rows || []);
      if (rows.length) renderChatChart(chatEl, cs, rows);
    }
    conversationHistory.push({role:'user', content:question});
    conversationHistory.push({role:'assistant', content:answer});
    if (conversationHistory.length > MAX_TURNS * 2) conversationHistory = conversationHistory.slice(-MAX_TURNS * 2);
    _autoSave(uid(), currentSessionId, conversationHistory);
  } catch(e) {
    aiDiv.innerHTML = '<div class="chat-ai-header"><div class="chat-ai-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><span class="chat-ai-name">DMS AI</span></div><div class="chat-ai-body"><span class="chat-error">⚠️ '+e.message+'</span></div>';
  }
  chatEl.scrollTop = chatEl.scrollHeight;
}

function openAiModal()  { document.getElementById('aiReportModal').classList.add('show'); }
function closeAiModal() { document.getElementById('aiReportModal').classList.remove('show'); }
function openSidebar()  { document.getElementById('sidebar').classList.add('open'); document.getElementById('sidebarOverlay').classList.add('visible'); }
function closeSidebar() { document.getElementById('sidebar').classList.remove('open'); document.getElementById('sidebarOverlay').classList.remove('visible'); }

document.addEventListener('DOMContentLoaded', function() {
  fetchStaff();
  switchView('chat');

  document.getElementById('staffSelect').addEventListener('change', function(e) {
    const selectedUid = e.target.value;
    localStorage.setItem('dms_staff_uid', selectedUid);
    updateStaffCard(selectedUid);
    if (selectedUid) { loadCurrentView(); initSessionsForUid(selectedUid); }
    else { currentSessionId = null; }
  });

  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', function(e) {
      e.preventDefault();
      switchView(el.dataset.view);
      closeSidebar();
      if (uid()) loadCurrentView();
    });
  });

  document.getElementById('chatSendBtn').addEventListener('click', handleChat);
  document.getElementById('chatInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChat(); }
  });

  document.getElementById('chatSuggestions').addEventListener('click', function(e) {
    if (e.target.classList.contains('suggest-chip')) { sendSuggestion(e.target.textContent); }
  });

  document.getElementById('chatHistoryBtn').addEventListener('click', function() {
    const panel = document.getElementById('chatHistPanel');
    const isOpen = panel.classList.contains('open');
    if (!isOpen) renderHistPanel();
    panel.classList.toggle('open', !isOpen);
  });
  document.getElementById('chatHistClose').addEventListener('click', () =>
    document.getElementById('chatHistPanel').classList.remove('open'));
  document.getElementById('chatHistNewBtn').addEventListener('click', function() {
    if (!uid()) { alert('Please select a staff member first.'); return; }
    startNewSession();
    document.getElementById('chatHistPanel').classList.remove('open');
  });
  document.getElementById('chatClearBtn').addEventListener('click', function() {
    if (!confirm('Start a new chat session?')) return;
    startNewSession();
  });

  document.getElementById('chatExportBtn').addEventListener('click', async function() {
    if (!lastChatExec || !lastChatExec.rows.length) { alert('No data to export yet.'); return; }
    try { await downloadXlsx('/api/export/xlsx', {columns: lastChatExec.columns, rows: lastChatExec.rows, filename:'dms_export_'+Date.now()+'.xlsx'}); }
    catch(e) { alert('Export failed: '+e.message); }
  });

  document.getElementById('chatAiReportBtn').addEventListener('click', function() {
    if (!lastChatExec || !lastChatExec.rows.length) { alert('No data to export yet.'); return; }
    openAiModal();
  });

  const aiModal = document.getElementById('aiReportModal');
  const aiReportErr = document.getElementById('aiReportErr');
  const aiGenBtn = document.getElementById('aiModalGenerate');
  const aiPromptEl = document.getElementById('aiReportPrompt');

  document.getElementById('aiModalClose').addEventListener('click', closeAiModal);
  document.getElementById('aiModalCancel').addEventListener('click', closeAiModal);
  aiModal.addEventListener('click', e => { if (e.target === aiModal) closeAiModal(); });
  document.querySelectorAll('.ai-modal-chip').forEach(chip => {
    chip.addEventListener('click', () => { aiPromptEl.value = chip.dataset.text; });
  });
  aiGenBtn.addEventListener('click', async function() {
    const promptText = (aiPromptEl.value || '').trim();
    if (!promptText) { aiReportErr.textContent = 'Please describe the report.'; aiReportErr.classList.add('show'); return; }
    if (!lastChatExec || !lastChatExec.rows.length) { closeAiModal(); return; }
    aiReportErr.classList.remove('show');
    aiGenBtn.disabled = true;
    aiGenBtn.innerHTML = '<span class="ai-modal-spinner"></span> Generating…';
    try {
      await downloadXlsx('/api/export/smart', {
        prompt: promptText, columns: lastChatExec.columns, rows: lastChatExec.rows,
        filename: 'DMS_Report_'+Date.now()+'.xlsx'
      });
      closeAiModal();
    } catch(e) { aiReportErr.textContent = e.message || 'Failed.'; aiReportErr.classList.add('show'); }
    finally { aiGenBtn.disabled = false; aiGenBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg> Generate Excel'; }
  });

  const batchPanel = document.getElementById('batchPanel');
  const batchTextarea = document.getElementById('batchTextarea');
  const batchProgress = document.getElementById('batchProgress');
  const batchRunBtn = document.getElementById('batchRunBtn');
  const batchStopBtn = document.getElementById('batchStopBtn');
  let batchRunning = false, batchStop = false;

  document.getElementById('chatBatchBtn').addEventListener('click', function() {
    batchPanel.style.display = batchPanel.style.display === 'block' ? 'none' : 'block';
  });
  document.getElementById('batchCloseBtn').addEventListener('click', function() {
    if (!batchRunning) batchPanel.style.display = 'none';
  });
  batchStopBtn.addEventListener('click', function() { batchStop = true; batchStopBtn.textContent = 'Stopping…'; batchStopBtn.disabled = true; });
  batchRunBtn.addEventListener('click', async function() {
    if (batchRunning) return;
    if (!uid()) { alert('Please select a staff member first.'); return; }
    const lines = batchTextarea.value.split('\n').map(l=>l.trim()).filter(l=>l);
    if (!lines.length) { alert('Enter at least one question.'); return; }
    batchRunning = true; batchStop = false;
    batchRunBtn.disabled = true; batchStopBtn.style.display = 'inline-flex';
    for (let i = 0; i < lines.length; i++) {
      if (batchStop) break;
      batchProgress.textContent = 'Running '+(i+1)+' / '+lines.length+': '+lines[i].substring(0,40);
      batchProgress.className = 'batch-progress running';
      if (i > 0) { const div = document.createElement('div'); div.className = 'batch-divider'; div.textContent = 'Question '+(i+1)+' of '+lines.length; document.getElementById('chatHistory').appendChild(div); }
      document.getElementById('chatInput').value = lines[i];
      await handleChat();
      await new Promise(r => setTimeout(r, 400));
    }
    batchRunning = false; batchRunBtn.disabled = false;
    batchStopBtn.style.display = 'none'; batchStopBtn.disabled = false; batchStopBtn.textContent = '■ Stop';
    batchProgress.className = 'batch-progress';
    batchProgress.textContent = batchStop ? 'Stopped.' : 'Done — all '+lines.length+' questions answered.';
  });

  document.getElementById('chatPdfBtn').addEventListener('click', function() {
    const msgCount = document.getElementById('chatHistory').querySelectorAll('.chat-message').length;
    if (msgCount <= 1) { alert('Start a conversation first.'); return; }
    const ts = document.createElement('div');
    ts.style.cssText = 'font-size:10pt;color:#888;margin-top:12px;padding-top:8px;border-top:1px solid #555;';
    ts.textContent = 'Generated: '+new Date().toLocaleString('en-IN')+'  |  Staff: '+(staffMap[uid()]||{}).name||uid();
    document.getElementById('chatHistory').appendChild(ts);
    window.print();
    setTimeout(() => ts.remove(), 500);
  });

  document.getElementById('btnRefresh').addEventListener('click', function() {
    if (uid()) loadCurrentView(); else alert('Please select a staff member first.');
  });

  document.getElementById('hamburger').addEventListener('click', openSidebar);
  document.getElementById('sidebarOverlay').addEventListener('click', closeSidebar);

  document.querySelectorAll('.qb-apply').forEach(btn => {
    btn.addEventListener('click', function() {
      const view = this.dataset.view;
      if (uid()) { try { execMulti(view, JSON.parse(this.dataset.flags)).then(() => {}); } catch(_) {} }
      else alert('Please select a staff member first.');
    });
  });

  document.querySelectorAll('.qb-reset').forEach(btn => {
    btn.addEventListener('click', function() {
      resetDates(this.dataset.view);
    });
  });

  get('/api/analytics/flags').then(data => {
    if (data && data.flags) {
      const sel = document.getElementById('groupFlagSelect');
      data.flags.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f; opt.textContent = f;
        sel.appendChild(opt);
      });
    }
  });

  document.getElementById('groupRunBtn').addEventListener('click', function() {
    if (uid()) loadGroup(); else alert('Please select a staff member first.');
  });

  document.getElementById('customQueryRunBtn').addEventListener('click', function() {
    loadCustomQuery();
  });

  document.getElementById('customQueryClearBtn').addEventListener('click', function() {
    document.getElementById('customSqlInput').value = '';
    document.getElementById('customQueryMeta').style.display = 'none';
    document.getElementById('customQueryTable').innerHTML = '<div class="empty-state"><div class="empty-icon">🔧</div>Write a SELECT query above and click Run Query.</div>';
  });

  const gmToggle = document.getElementById('godModeToggle');
  if (gmToggle) gmToggle.addEventListener('change', toggleGodMode);
});
