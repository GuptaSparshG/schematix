// Circuit Diagram Analyzer — frontend logic.
// SaaS-dashboard UI; talks to the FastAPI backend at /api/*.

const API = {
  analyze: body => fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => {
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || data.error || 'Request failed');
    return data;
  }),
  exportCsv: payload => fetch('/api/export/csv', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.ok ? r.blob() : Promise.reject(new Error('Export failed'))),
  history:    () => fetch('/api/history').then(r => r.json()),
  historyGet: id => fetch(`/api/history/${id}`).then(r => r.ok ? r.json() : Promise.reject(new Error('Not found'))),
  historyDel: id => fetch(`/api/history/${id}`, { method: 'DELETE' }),
  historyClear: () => fetch('/api/history', { method: 'DELETE' }),
  stlHistory:    () => fetch('/api/stl/history').then(r => r.json()),
  stlHistoryGet: id => fetch(`/api/stl/history/${id}`).then(r => r.ok ? r.json() : Promise.reject(new Error('Not found'))),
  stlHistoryDel: id => fetch(`/api/stl/history/${id}`, { method: 'DELETE' }),
  stlHistoryClear: () => fetch('/api/stl/history', { method: 'DELETE' }),
  cost: body => fetch('/api/cost-analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => {
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || data.error || 'Cost analysis failed');
    return data;
  }),
};

const state = {
  imageSource: null,
  lastResult: null,
  lastCost: null,
  currentHistoryId: null,
  currentView: 'analyzer',
};

const $ = s => document.querySelector(s);

const els = {
  uploadZone:    $('#upload-zone'),
  fileInput:     $('#file-input'),
  preview:       $('#preview'),
  previewEmpty:  $('#preview-empty'),
  pathLabel:     $('#path-label'),
  analyzeBtn:    $('#analyze-btn'),
  exportBtn:     $('#export-btn'),
  status:        $('#status'),
  // Stats
  statTotal:     $('#stat-total'),
  statTotalDelta:$('#stat-total-delta'),
  statCats:      $('#stat-cats'),
  statCatsDelta: $('#stat-cats-delta'),
  statLatency:   $('#stat-latency'),
  statLatencyDelta: $('#stat-latency-delta'),
  // Breakdown / BOM
  breakdown:     $('#breakdown'),
  bomBody:       $('#bom-body'),
  bomSub:        $('#bom-sub'),
  bomSearch:     $('#bom-search'),
  summaryCard:   $('#summary-card'),
  summaryText:   $('#summary-text'),
};

document.addEventListener('DOMContentLoaded', () => {
  bindEvents();
});

function bindEvents() {
  els.uploadZone.addEventListener('click', () => els.fileInput.click());
  els.uploadZone.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      els.fileInput.click();
    }
  });
  els.fileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    handleFile(file);
    e.target.value = '';  // allow re-selecting the same file
  });

  ['dragenter', 'dragover'].forEach(ev =>
    els.uploadZone.addEventListener(ev, e => {
      e.preventDefault();
      els.uploadZone.classList.add('drag');
    })
  );
  ['dragleave', 'drop'].forEach(ev =>
    els.uploadZone.addEventListener(ev, e => {
      e.preventDefault();
      els.uploadZone.classList.remove('drag');
    })
  );
  els.uploadZone.addEventListener('drop', e => {
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  els.analyzeBtn.addEventListener('click', runAnalyze);
  els.exportBtn.addEventListener('click', exportCsv);

  els.bomSearch.addEventListener('input', () => {
    const q = els.bomSearch.value.trim().toLowerCase();
    Array.from(els.bomBody.querySelectorAll('tr')).forEach(r => {
      const hit = !q || r.textContent.toLowerCase().includes(q);
      r.style.display = hit ? '' : 'none';
    });
  });

  // View switching via sidebar nav
  document.querySelectorAll('.nav-item[data-view]').forEach(n => {
    n.addEventListener('click', e => {
      e.preventDefault();
      switchView(n.dataset.view);
    });
  });

  // Cost analysis
  const costRefresh = document.getElementById('cost-refresh');
  if (costRefresh) costRefresh.addEventListener('click', runCostAnalysis);

  // STL view
  bindStlEvents();

  const costSearch = document.getElementById('cost-search');
  if (costSearch) {
    costSearch.addEventListener('input', () => {
      const q = costSearch.value.trim().toLowerCase();
      Array.from(document.querySelectorAll('#cost-body tr')).forEach(r => {
        const hit = !q || r.textContent.toLowerCase().includes(q);
        r.style.display = hit ? '' : 'none';
      });
    });
  }
}

function switchView(view) {
  state.currentView = view;
  document.querySelectorAll('.nav-item[data-view]').forEach(n => {
    n.classList.toggle('active', n.dataset.view === view);
  });
  document.getElementById('view-analyzer').hidden = view !== 'analyzer';
  document.getElementById('view-cost').hidden     = view !== 'cost';
  document.getElementById('view-stl').hidden         = view !== 'stl';
  document.getElementById('view-stl-history').hidden = view !== 'stl-history';
  document.getElementById('view-history').hidden     = view !== 'history';

  // Swap the page title/subtitle by service
  const titles = {
    analyzer:     ['Schematix · Circuit Analyzer',  'Identify every component in your schematic in seconds'],
    cost:         ['Schematix · Cost Analysis',     'Compare per-component prices across 6 sourcing sites'],
    history:      ['Schematix · Circuit History',   'Last 20 circuit analyses · click any card to reopen'],
    stl:          ['Schematix · Draft Studio',      'Convert 3D STL meshes to clean 2D engineering drawings'],
    'stl-history':['Schematix · Drawing History',   'Last 20 generated STL drawings · click any card to reopen'],
  };
  const t = titles[view] || titles.analyzer;
  document.getElementById('page-title').textContent = t[0];
  document.getElementById('page-sub').textContent   = t[1];

  if (view === 'stl' || view === 'stl-history') loadStlHistory();

  // Enable cost refresh only if we have an analysis result
  const costRefresh = document.getElementById('cost-refresh');
  if (costRefresh) costRefresh.disabled = !state.lastResult;

  // Auto-run cost analysis on first visit if we have an analysis but no pricing yet
  if (view === 'cost' && state.lastResult && !state.lastCost) {
    runCostAnalysis();
  }

  // Refresh history list when entering the history tab
  if (view === 'history') {
    loadHistory();
  }
}

// ── file upload
function handleFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    state.imageSource = {
      kind: 'upload',
      name: file.name,
      b64: reader.result,
    };
    showPreview(reader.result, file.name);
  };
  reader.readAsDataURL(file);
}

function showPreview(src, name) {
  els.preview.src = src;
  els.preview.hidden = false;
  els.previewEmpty.hidden = true;
  els.pathLabel.textContent = name;
  els.analyzeBtn.disabled = false;
}

// ── analyze
async function runAnalyze() {
  if (!state.imageSource) return;

  setStatus('Calling Gemini…', 'working');
  els.analyzeBtn.disabled = true;
  els.exportBtn.disabled = true;
  toggleSpinner(true);
  showWorking();

  const body = {};
  if (state.imageSource.kind === 'sample') {
    body.sample = state.imageSource.name;
  } else {
    body.image_b64 = state.imageSource.b64;
    body.filename = state.imageSource.name;
  }

  try {
    const data = await API.analyze(body);
    state.lastResult = data;
    state.lastCost = null;
    state.currentHistoryId = data._meta?.history_id || null;
    renderResults(data);
    setStatus(`Done · ${data._meta?.elapsed_s ?? '?'}s`, 'ok');
    els.exportBtn.disabled = false;
    els.bomSearch.disabled = false;
  } catch (err) {
    showError(err.message);
    setStatus('Failed', 'err');
  } finally {
    els.analyzeBtn.disabled = false;
    toggleSpinner(false);
  }
}

function setStatus(text, state = 'idle') {
  els.status.textContent = text;
  els.status.dataset.state = state;
}

function toggleSpinner(on) {
  const label = els.analyzeBtn.querySelector('.btn-label');
  const spin  = els.analyzeBtn.querySelector('.cta-spinner');
  if (on) {
    label.innerHTML = 'Analyzing…';
    spin.hidden = false;
  } else {
    label.innerHTML = '<i class="bi bi-search"></i> Analyze circuit';
    spin.hidden = true;
  }
}

function showWorking() {
  els.breakdown.innerHTML = `
    <div class="empty">
      <i class="bi bi-hourglass-split" style="opacity: 0.7;"></i>
      <div>Analyzing…</div>
      <small>Gemini is identifying components. Usually 5–9s.</small>
    </div>`;
  els.bomBody.innerHTML = `<tr><td colspan="4" class="empty-cell">Working — results will appear here.</td></tr>`;
  els.summaryCard.hidden = true;
}

function showError(msg) {
  els.breakdown.innerHTML = `
    <div class="empty">
      <i class="bi bi-exclamation-triangle-fill" style="color: var(--danger);"></i>
      <div style="color: var(--danger-ink);">Analysis failed</div>
      <small style="white-space: pre-wrap; display: block; margin-top: 6px;">${escapeHtml(msg)}</small>
    </div>`;
  els.bomBody.innerHTML = `<tr><td colspan="4" class="empty-cell">No data — fix the error above and retry.</td></tr>`;
}

// ── render
function renderResults(data) {
  const components = data.components || [];
  const total = data.total_count ?? components.reduce((s, c) => s + (c.items || []).length, 0);
  const elapsed = data._meta?.elapsed_s ?? '—';

  // Stat cards
  animateCount(els.statTotal, total);
  els.statTotalDelta.className = 'chip chip-success';
  els.statTotalDelta.innerHTML = `<i class="bi bi-check2"></i> Done`;
  els.statCats.textContent = components.filter(c => (c.items || []).length).length;
  els.statCatsDelta.className = 'chip chip-primary';
  els.statCatsDelta.innerHTML = `<i class="bi bi-grid"></i> ${data.title || 'Circuit'}`;
  els.statLatency.textContent = `${elapsed}s`;
  els.statLatencyDelta.className = 'chip ' + (elapsed !== '—' && elapsed < 7 ? 'chip-success' : 'chip-warning');
  els.statLatencyDelta.innerHTML = `<i class="bi bi-stopwatch"></i> Gemini`;

  // Rich per-category cards with item lists
  els.breakdown.innerHTML = '';
  els.breakdown.classList.add('fadein');
  const max = Math.max(1, ...components.map(c => (c.items || []).length));
  const grid = document.createElement('div');
  grid.className = 'category-grid';
  components.forEach(cat => {
    const items = cat.items || [];
    if (!items.length) return;
    const count = items.length;
    const widthPct = (count / max) * 100;

    const card = document.createElement('div');
    card.className = 'category-card';
    card.innerHTML = `
      <div class="cc-head">
        <span class="cc-name">${escapeHtml(cat.category || '—')}</span>
        <span class="cc-count">${count}</span>
      </div>
      <div class="cc-bar"><div class="cc-fill" style="width: ${widthPct}%;"></div></div>
      <ul class="cc-items"></ul>
    `;
    const ul = card.querySelector('.cc-items');
    items.forEach(item => {
      const li = document.createElement('li');
      const value = item.value || '';
      const typ = item.type || '';
      li.innerHTML = `
        <span class="cc-lbl">${escapeHtml(item.label || '—')}</span>
        <span class="cc-val">${escapeHtml(value)}</span>
        ${typ ? `<span class="cc-typ">${escapeHtml(typ)}</span>` : '<span></span>'}`;
      ul.appendChild(li);
    });
    grid.appendChild(card);
  });
  els.breakdown.appendChild(grid);

  // BOM table
  els.bomBody.innerHTML = '';
  components.forEach(cat => {
    const cname = cat.category || '';
    (cat.items || []).forEach(item => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><span class="cat-chip">${escapeHtml(cname)}</span></td>
        <td class="lbl-cell">${escapeHtml(item.label || '—')}</td>
        <td>${escapeHtml(item.value || '')}</td>
        <td>${escapeHtml(item.type || '')}</td>`;
      els.bomBody.appendChild(tr);
    });
  });
  if (!els.bomBody.children.length) {
    els.bomBody.innerHTML = `<tr><td colspan="4" class="empty-cell">No components identified.</td></tr>`;
  }
  els.bomSub.textContent = `${total} components across ${components.length} categories · ${data.title || ''}`;

  // Summary
  if (data.summary) {
    els.summaryCard.hidden = false;
    els.summaryText.textContent = ' ' + data.summary;
  } else {
    els.summaryCard.hidden = true;
  }
}

function animateCount(el, target, duration = 700) {
  const start = 0;
  const t0 = performance.now();
  function tick(now) {
    const t = Math.min(1, (now - t0) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ── export
async function exportCsv() {
  if (!state.lastResult) return;
  try {
    const blob = await API.exportCsv(state.lastResult);
    const name = (state.lastResult._meta?.image || 'bom').replace(/\.[^.]+$/, '') + '.csv';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Export failed: ' + err.message);
  }
}

// ── STL → 2D drawing
const stlState = { file: null, lastUrl: null };

function bindStlEvents() {
  const drop = document.getElementById('stl-drop');
  const input = document.getElementById('stl-file-input');
  const gen = document.getElementById('stl-generate');
  const dl  = document.getElementById('stl-download');
  if (!drop) return;

  drop.addEventListener('click', () => input.click());
  drop.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
  });
  input.addEventListener('change', e => {
    handleStlFile(e.target.files[0]);
    e.target.value = '';
  });
  ['dragenter', 'dragover'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); })
  );
  ['dragleave', 'drop'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); })
  );
  drop.addEventListener('drop', e => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f && f.name.toLowerCase().endsWith('.stl')) handleStlFile(f);
  });

  gen.addEventListener('click', runStlGenerate);
  dl.addEventListener('click', () => {
    if (stlState.lastUrl) window.open(stlState.lastUrl + '?download=1', '_blank');
  });

  const clearBtn = document.getElementById('stl-history-clear');
  if (clearBtn) clearBtn.addEventListener('click', async () => {
    if (!confirm('Clear ALL STL drawing history? This deletes the PNG files too.')) return;
    await API.stlHistoryClear();
    loadStlHistory();
  });
}

function handleStlFile(file) {
  if (!file) return;
  stlState.file = file;
  document.getElementById('stl-filename').textContent = file.name;
  document.getElementById('stl-generate').disabled = false;
}

async function runStlGenerate() {
  if (!stlState.file) return;
  const gen = document.getElementById('stl-generate');
  const dl  = document.getElementById('stl-download');
  const previewWrap = document.getElementById('stl-preview-wrap');
  const label = gen.querySelector('.btn-label');
  const spin  = gen.querySelector('.cta-spinner');

  gen.disabled = true;
  dl.disabled = true;
  label.innerHTML = 'Rendering…';
  spin.hidden = false;
  previewWrap.innerHTML = `
    <div class="empty" style="text-align:center;padding:60px 20px;color:var(--muted);">
      <div class="cta-spinner" style="border-top-color:var(--text);margin:0 auto 10px;width:24px;height:24px;border-width:3px;"></div>
      <div>Rendering orthographic views…</div>
      <small>Loading mesh, projecting Front / Side / Top / Isometric</small>
    </div>`;

  const fd = new FormData();
  fd.append('file', stlState.file);
  fd.append('drawn_by', document.getElementById('stl-drawn-by').value || 'Engineer');
  fd.append('line_width', document.getElementById('stl-line-width').value);
  fd.append('dpi', document.getElementById('stl-dpi').value);

  try {
    const res = await fetch('/api/stl/generate', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.error || 'Render failed');

    stlState.lastUrl = data.preview_url;
    previewWrap.innerHTML = `<img src="${data.preview_url}" alt="STL drawing" class="stl-preview-img" />`;
    dl.disabled = false;
    loadStlHistory();
  } catch (err) {
    previewWrap.innerHTML = `<div class="empty" style="text-align:center;padding:60px 20px;color:var(--danger);">❌ ${escapeHtml(err.message)}</div>`;
  } finally {
    gen.disabled = false;
    label.innerHTML = '<i class="bi bi-box-arrow-up-right"></i> Generate drawing';
    spin.hidden = true;
  }
}

async function loadStlHistory() {
  const grid = document.getElementById('stl-history-grid');
  if (!grid) return;
  grid.innerHTML = `<div class="empty" style="text-align:center;padding:30px;color:var(--muted);grid-column:1/-1;">Loading…</div>`;
  try {
    const entries = await API.stlHistory();
    renderStlHistory(entries);
  } catch (err) {
    grid.innerHTML = `<div class="empty" style="text-align:center;padding:30px;color:var(--danger);grid-column:1/-1;">❌ ${escapeHtml(err.message)}</div>`;
  }
}

function renderStlHistory(entries) {
  const grid = document.getElementById('stl-history-grid');
  const sub  = document.getElementById('stl-history-sub');
  if (!entries.length) {
    sub.textContent = 'No drawings yet — generate one above.';
    grid.innerHTML = `<div class="empty" style="text-align:center;padding:40px;color:var(--muted);grid-column:1/-1;">
      <i class="bi bi-rulers" style="font-size:28px;opacity:0.4;display:block;margin-bottom:8px;"></i>
      <div>No STL drawings yet</div>
      <small>Each generated drawing is auto-saved here (last 20).</small>
    </div>`;
    return;
  }
  sub.textContent = `Showing ${entries.length} of last 20 drawings · click any card to reopen`;
  grid.innerHTML = '';
  entries.forEach(e => {
    const when = new Date((e.timestamp || 0) * 1000).toLocaleString();
    const card = document.createElement('div');
    card.className = 'history-card';
    card.innerHTML = `
      <img class="hc-thumb" src="${e.preview_url}" alt="" />
      <div class="hc-body">
        <div class="hc-title">${escapeHtml(e.stl_filename || 'Drawing')}</div>
        <div class="hc-meta">
          <span class="chip chip-primary"><i class="bi bi-rulers"></i> ${e.dpi} dpi</span>
          <span class="chip chip-muted"><i class="bi bi-vector-pen"></i> lw ${e.line_width}</span>
          <span class="chip chip-muted"><i class="bi bi-person"></i> ${escapeHtml(e.drawn_by || '')}</span>
        </div>
        <div class="hc-foot">
          <span class="hc-file">${escapeHtml(e.output_filename || '')}</span>
          <span class="hc-when">${escapeHtml(when)}</span>
        </div>
      </div>
      <button class="hc-del" title="Delete" data-id="${e.id}"><i class="bi bi-trash"></i></button>
    `;
    card.addEventListener('click', ev => {
      if (ev.target.closest('.hc-del')) return;
      // Show this drawing in the preview pane and enable download
      stlState.lastUrl = e.preview_url;
      document.getElementById('stl-preview-wrap').innerHTML =
        `<img src="${e.preview_url}" alt="" class="stl-preview-img" />`;
      document.getElementById('stl-filename').textContent = e.stl_filename || '(from history)';
      document.getElementById('stl-download').disabled = false;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    card.querySelector('.hc-del').addEventListener('click', async ev => {
      ev.stopPropagation();
      if (!confirm('Delete this drawing?')) return;
      await API.stlHistoryDel(e.id);
      loadStlHistory();
    });
    grid.appendChild(card);
  });
}

// ── history
async function loadHistory() {
  const grid = document.getElementById('history-grid');
  grid.innerHTML = `<div class="empty" style="text-align:center;padding:40px;color:var(--muted);grid-column:1/-1;"><i class="bi bi-arrow-clockwise" style="font-size:24px;opacity:0.5;"></i><div>Loading…</div></div>`;
  try {
    const entries = await API.history();
    renderHistory(entries);
  } catch (err) {
    grid.innerHTML = `<div class="empty" style="text-align:center;padding:40px;color:var(--danger);grid-column:1/-1;">❌ ${escapeHtml(err.message)}</div>`;
  }
}

function renderHistory(entries) {
  const grid = document.getElementById('history-grid');
  const sub = document.getElementById('history-sub');
  if (!entries.length) {
    sub.textContent = 'No analyses yet — run one in the Analyzer tab.';
    grid.innerHTML = `<div class="empty" style="text-align:center;padding:60px;color:var(--muted);grid-column:1/-1;">
      <i class="bi bi-clock-history" style="font-size:32px;opacity:0.4;display:block;margin-bottom:8px;"></i>
      <div>No history yet</div>
      <small>Each analysis you run is auto-saved here (last 20).</small>
    </div>`;
    return;
  }

  sub.textContent = `Showing ${entries.length} of last 20 runs · click any card to reload it`;
  grid.innerHTML = '';
  entries.forEach(e => {
    const card = document.createElement('div');
    card.className = 'history-card';
    card.dataset.id = e.id;
    const when = new Date((e.timestamp || 0) * 1000).toLocaleString();
    const thumb = e.thumbnail
      ? `<img class="hc-thumb" src="${e.thumbnail}" alt="" />`
      : `<div class="hc-thumb hc-thumb-empty"><i class="bi bi-image"></i></div>`;
    card.innerHTML = `
      ${thumb}
      <div class="hc-body">
        <div class="hc-title">${escapeHtml(e.title || 'Circuit')}</div>
        <div class="hc-meta">
          <span class="chip chip-primary"><i class="bi bi-cpu"></i> ${e.total_count ?? 0}</span>
          <span class="chip chip-muted"><i class="bi bi-tags"></i> ${e.category_count ?? 0}</span>
          ${e.elapsed_s != null ? `<span class="chip chip-muted"><i class="bi bi-stopwatch"></i> ${e.elapsed_s}s</span>` : ''}
        </div>
        <div class="hc-foot">
          <span class="hc-file">${escapeHtml(e.image_name || '')}</span>
          <span class="hc-when">${escapeHtml(when)}</span>
        </div>
      </div>
      <button class="hc-del" title="Delete" data-id="${e.id}"><i class="bi bi-trash"></i></button>
    `;
    card.addEventListener('click', ev => {
      if (ev.target.closest('.hc-del')) return;
      loadFromHistory(e.id);
    });
    card.querySelector('.hc-del').addEventListener('click', async ev => {
      ev.stopPropagation();
      if (!confirm('Delete this analysis from history?')) return;
      await API.historyDel(e.id);
      loadHistory();
    });
    grid.appendChild(card);
  });
}

async function loadFromHistory(id) {
  try {
    const entry = await API.historyGet(id);
    const result = entry.result || {};
    state.lastResult = result;
    state.lastCost = entry.cost || null;        // <-- restore prior pricing
    state.currentHistoryId = id;

    // Restore preview from thumbnail
    if (entry.thumbnail) {
      showPreview(entry.thumbnail, entry.image_name || '(from history)');
    } else {
      els.pathLabel.textContent = entry.image_name || '(from history)';
    }
    state.imageSource = { kind: 'history', name: entry.image_name, id };

    // Re-render results
    renderResults(result);
    if (state.lastCost) renderCost(state.lastCost);

    setStatus(`Loaded · ${result.total_count || 0} components${state.lastCost ? ' · pricing cached' : ''}`, 'ok');
    els.exportBtn.disabled = false;
    els.bomSearch.disabled = false;

    switchView('analyzer');
  } catch (err) {
    alert('Could not load entry: ' + err.message);
  }
}

document.addEventListener('click', e => {
  if (e.target.closest('#history-clear')) {
    if (!confirm('Clear ALL history? This cannot be undone.')) return;
    API.historyClear().then(loadHistory);
  }
});

// ── cost analysis
async function runCostAnalysis() {
  if (!state.lastResult) {
    alert('Run a circuit analysis first.');
    return;
  }
  const components = state.lastResult.components || [];
  if (!components.length) {
    alert('No components in the current analysis.');
    return;
  }

  const refreshBtn = document.getElementById('cost-refresh');
  refreshBtn.disabled = true;
  refreshBtn.innerHTML = '<span class="cta-spinner" style="border-top-color:var(--text);"></span> Pricing…';

  const costBody = document.getElementById('cost-body');
  costBody.innerHTML = `<tr><td colspan="6" class="empty-cell">⏳ Searching the web for component prices…</td></tr>`;

  // Show the prominent loader banner
  const loader = document.getElementById('cost-loader');
  const loaderSub = document.getElementById('cost-loader-sub');
  const chips = Array.from(document.querySelectorAll('#cost-loader-sites .cl-chip'));
  chips.forEach(c => c.classList.remove('active', 'done'));
  loader.hidden = false;
  // Restart the progress bar animation
  const fill = loader.querySelector('.cl-progress-fill');
  fill.style.animation = 'none';
  // force reflow so the animation restarts
  fill.offsetHeight; // eslint-disable-line no-unused-expressions
  fill.style.animation = '';

  // Rotate the active chip every 3 seconds
  let active = 0;
  const cycleChip = () => {
    chips.forEach((c, idx) => {
      c.classList.toggle('active', idx === active);
      c.classList.toggle('done',   idx < active);
    });
    loaderSub.textContent = `Querying ${chips[active].dataset.site} for ${components.length} components…`;
    active = (active + 1) % chips.length;
  };
  cycleChip();
  const tickHandle = setInterval(cycleChip, 3000);

  try {
    const body = { components, history_id: state.currentHistoryId || undefined };
    const data = await API.cost(body);
    state.lastCost = data;
    renderCost(data);
  } catch (err) {
    costBody.innerHTML = `<tr><td colspan="6" class="empty-cell" style="color:var(--danger);">❌ ${escapeHtml(err.message)}</td></tr>`;
  } finally {
    clearInterval(tickHandle);
    loader.hidden = true;
    chips.forEach(c => c.classList.remove('active', 'done'));
    refreshBtn.disabled = !state.lastResult;
    refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Re-run pricing';
  }
}

function renderCost(data) {
  const comps = data.components || [];
  const total = data.total_min_cost_usd ?? 0;
  const cheapest = data.cheapest_site || '—';
  const elapsed = data._meta?.elapsed_s ?? '—';
  const totalsBySite = data.totals_by_site || {};

  // Stat cards
  document.getElementById('cost-total').textContent    = `$${total.toFixed(2)}`;
  document.getElementById('cost-cheapest').textContent = cheapest;
  document.getElementById('cost-count').textContent    = comps.length;
  document.getElementById('cost-latency').textContent  = `${elapsed}s`;

  // Per-site totals
  const siteEl = document.getElementById('site-totals');
  siteEl.innerHTML = '';
  const grid = document.createElement('div');
  grid.className = 'site-grid';
  const sorted = Object.entries(totalsBySite).sort((a, b) => a[1] - b[1]);
  const minTotal = sorted[0] ? sorted[0][1] : 0;
  sorted.forEach(([site, sum]) => {
    const card = document.createElement('div');
    card.className = 'site-card' + (site === cheapest ? ' site-card-best' : '');
    card.innerHTML = `
      <div class="site-name">${escapeHtml(site)}${site === cheapest ? ' <span class="chip chip-success" style="margin-left:6px;">cheapest</span>' : ''}</div>
      <div class="site-total">$${sum.toFixed(2)}</div>
      <div class="site-delta">${site === cheapest ? 'best' : `+$${(sum - minTotal).toFixed(2)}`}</div>`;
    grid.appendChild(card);
  });
  siteEl.appendChild(grid);

  // Per-component table
  const tbody = document.getElementById('cost-body');
  tbody.innerHTML = '';
  comps.forEach(c => {
    const sources = c.sources || [];
    const sourcesHtml = sources.map(s => {
      const isMin = s.site === c.min_site;
      return `<span class="src-pill${isMin ? ' src-pill-min' : ''}">${escapeHtml(s.site)} · $${(s.price_usd || 0).toFixed(2)}</span>`;
    }).join(' ');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="lbl-cell">${escapeHtml(c.label || '—')}</td>
      <td>${escapeHtml(c.value || '')}</td>
      <td><span class="cat-chip">${escapeHtml(c.category || '')}</span></td>
      <td class="min-price">$${(c.min_price_usd || 0).toFixed(2)}</td>
      <td><strong>${escapeHtml(c.min_site || '—')}</strong></td>
      <td class="src-cell">${sourcesHtml}</td>`;
    tbody.appendChild(tr);
  });
  if (!comps.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No pricing returned.</td></tr>`;
  }

  const sourceLabel = data.source === 'google_search_grounded'
    ? '🌐 Real prices via Google Search'
    : '📊 Estimated from Gemini training data';
  document.getElementById('cost-sub').innerHTML =
    `${comps.length} components priced · cheapest: <strong>${escapeHtml(cheapest)}</strong> · ${elapsed}s · <span class="${data.source === 'google_search_grounded' ? 'text-success' : 'text-muted-strong'}">${sourceLabel}</span>`;
  document.getElementById('cost-search').disabled = comps.length === 0;
}

// ── util
function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}