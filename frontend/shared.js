// shared.js — Common UI helpers (topbar user, toasts, theme, sidebar resize).

// ---------- Topbar user panel ----------

function renderTopbarUser(session) {
  const el = document.getElementById('topbar-user');
  if (!el || !session) return;
  const display = session.name || session.full_name || session.username;
  const initials = (display || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
  const roleLbl = session.role_label || session.role || '';
  el.innerHTML = `
    <div class="user-avatar">${initials}</div>
    <div class="user-info">
      <span class="user-name">${display}</span>
      <span class="user-role">${roleLbl}</span>
    </div>
    <span class="role-badge ${session.level}">${session.level}</span>
  `;
}

// ---------- Toast notifications (con spinner + chiusura manuale) ----------

const _toastMap = new Map(); // id → { el, timerId }

function showToast(msg, type = 'success', opts = {}) {
  // opts: { id, loading, duration, detail }
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  // Se esiste già un toast con questo id, aggiornalo
  if (opts.id && _toastMap.has(opts.id)) {
    const existing = _toastMap.get(opts.id);
    clearTimeout(existing.timerId);
    _updateToast(existing.el, msg, type, opts);
    if (!opts.loading) {
      const dur = opts.duration ?? 4000;
      existing.timerId = setTimeout(() => {
        existing.el.classList.add('toast-fade-out');
        setTimeout(() => { existing.el.remove(); _toastMap.delete(opts.id); }, 300);
      }, dur);
    }
    return opts.id;
  }

  const icons = { success: 'check_circle', danger: 'error', warning: 'warning', info: 'info' };
  const colors = { success: 'var(--success)', danger: 'var(--danger)', warning: 'var(--warning)', info: 'var(--info)' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  _updateToast(toast, msg, type, opts);
  container.appendChild(toast);

  const toastId = opts.id || ('t_' + Date.now());
  let timerId = null;
  if (!opts.loading) {
    const dur = opts.duration ?? (type === 'danger' ? 6000 : 3500);
    timerId = setTimeout(() => {
      toast.classList.add('toast-fade-out');
      setTimeout(() => { toast.remove(); _toastMap.delete(toastId); }, 300);
    }, dur);
  }
  _toastMap.set(toastId, { el: toast, timerId });
  return toastId;
}

function _updateToast(el, msg, type, opts = {}) {
  const colors = { success: 'var(--success)', danger: 'var(--danger)', warning: 'var(--warning)', info: 'var(--info)' };
  const icons  = { success: 'check_circle', danger: 'error', warning: 'warning', info: 'info' };
  el.className = `toast ${type}`;
  const iconHtml = opts.loading
    ? `<span class="toast-spinner"></span>`
    : `<span class="material-symbols-rounded" style="color:${colors[type]||colors.info};font-size:18px;flex-shrink:0">${icons[type]||'info'}</span>`;
  const detailHtml = opts.detail
    ? `<div class="toast-detail">${opts.detail}</div>`
    : '';
  el.innerHTML = `
    ${iconHtml}
    <div style="flex:1;min-width:0">
      <div>${msg}</div>
      ${detailHtml}
    </div>
    <button onclick="this.closest('.toast').remove()" style="background:none;border:none;cursor:pointer;color:var(--text-dim);padding:0;display:flex;align-items:center;flex-shrink:0">
      <span class="material-symbols-rounded" style="font-size:16px">close</span>
    </button>`;
}

function dismissToast(id) {
  if (!_toastMap.has(id)) return;
  const { el, timerId } = _toastMap.get(id);
  clearTimeout(timerId);
  el.classList.add('toast-fade-out');
  setTimeout(() => { el.remove(); _toastMap.delete(id); }, 300);
}

// ---------- Task toast (spinner → risultato) ----------
// Uso: const tid = showTaskToast('Migrazione avviata…');
//      dismissTaskToast(tid, true, 'Completata');
function showTaskToast(msg) {
  return showToast(msg, 'info', { loading: true });
}
function finishTaskToast(id, success, msg, detail) {
  const type = success ? 'success' : 'danger';
  if (_toastMap.has(id)) {
    const { el, timerId } = _toastMap.get(id);
    clearTimeout(timerId);
    _updateToast(el, msg, type, { detail });
    const dur = success ? 4000 : 8000;
    const newTimer = setTimeout(() => {
      el.classList.add('toast-fade-out');
      setTimeout(() => { el.remove(); _toastMap.delete(id); }, 300);
    }, dur);
    _toastMap.set(id, { el, timerId: newTimer });
  }
}

// ---------- Theme ----------

function initTheme() {
  const saved = localStorage.getItem('pmx_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('pmx_theme', next);
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) btn.querySelector('span').textContent = next === 'dark' ? 'light_mode' : 'dark_mode';
}
initTheme();

// ---------- Sidebar resize ----------

function initSidebarResize(sidebarEl, shellEl) {
  const handle = sidebarEl.querySelector('.resize-handle');
  if (!handle) return;
  let dragging = false;
  handle.addEventListener('mousedown', e => {
    e.preventDefault(); dragging = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const w = Math.max(180, Math.min(400, e.clientX));
    sidebarEl.style.width = w + 'px';
    shellEl.style.gridTemplateColumns = w + 'px 1fr';
  });
  document.addEventListener('mouseup', () => {
    dragging = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
}

// ---------- Sidebar toggle ----------

function initSidebarToggle(shellEl) {
  const btn = document.getElementById('sidebar-toggle-btn');
  if (!btn) return;
  btn.addEventListener('click', () => shellEl.classList.toggle('sidebar-collapsed'));
}

// ---------- Cluster data cache ----------

let CLUSTER_DATA = null;   // normalized tree of the *active* credential
let CLUSTER_RAW  = null;
let ALL_CLUSTERS = null;   // [{cred_id, cred_name, host, online, tree:normalized, raw, error}, ...]

async function refreshClusterData() {
  const credId = getActiveCred();
  if (!credId) { CLUSTER_DATA = null; CLUSTER_RAW = null; return null; }
  try {
    const tree = await clusterApi.tree(credId);
    CLUSTER_RAW  = tree;
    CLUSTER_DATA = normalizeTree(tree);
    return CLUSTER_DATA;
  } catch (e) {
    CLUSTER_DATA = { nodes: [], vms: [], clusters: [], backupServers: [] };
    CLUSTER_RAW = null;
    return CLUSTER_DATA;
  }
}

async function refreshAllClusters() {
  try {
    const items = await clusterApi.allTrees();
    ALL_CLUSTERS = items.map(it => ({
      cred_id:   it.cred_id,
      cred_name: it.cred_name,
      host:      it.host,
      port:      it.port,
      online:    !!it.online,
      raw:       it.tree || null,
      tree:      it.tree ? normalizeTree(it.tree) : { nodes: [], vms: [], clusters: [], backupServers: [] },
      error:     it.error || null,
    }));
    return ALL_CLUSTERS;
  } catch (e) {
    ALL_CLUSTERS = [];
    return ALL_CLUSTERS;
  }
}

async function ensureClusterData() {
  if (!CLUSTER_DATA) await refreshClusterData();
  if (!ALL_CLUSTERS) await refreshAllClusters();
  return CLUSTER_DATA;
}

async function ensureAllClusters() {
  if (!ALL_CLUSTERS) await refreshAllClusters();
  return ALL_CLUSTERS;
}

// ---------- Error modal (Proxmox-style detailed error) ----------

function showErrorModal(title, msg, detail) {
  let modal = document.getElementById('pmx-error-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'pmx-error-modal';
    modal.className = 'pmx-error-overlay';
    modal.innerHTML = `
      <div class="pmx-error-modal" role="dialog">
        <div class="pmx-error-header">
          <span class="material-symbols-rounded" style="color:var(--danger);font-size:22px">error</span>
          <span id="pmx-error-title" style="flex:1;font-weight:700;font-size:14px"></span>
          <button class="pmx-error-close" onclick="closeErrorModal()" aria-label="Chiudi">
            <span class="material-symbols-rounded">close</span>
          </button>
        </div>
        <div class="pmx-error-body">
          <div id="pmx-error-msg" style="font-size:13px;color:var(--text);margin-bottom:10px;white-space:pre-wrap"></div>
          <details id="pmx-error-details-wrap" style="margin-top:8px">
            <summary style="cursor:pointer;font-size:12px;color:var(--text-muted)">Dettagli tecnici (Proxmox)</summary>
            <pre id="pmx-error-detail" class="pmx-error-pre"></pre>
          </details>
        </div>
        <div class="pmx-error-footer">
          <button class="btn btn-secondary btn-sm" onclick="copyErrorDetail()">
            <span class="material-symbols-rounded">content_copy</span> Copia
          </button>
          <button class="btn btn-primary btn-sm" onclick="closeErrorModal()">Chiudi</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
  }
  document.getElementById('pmx-error-title').textContent = title || 'Errore';
  document.getElementById('pmx-error-msg').textContent = msg || '';
  const detEl = document.getElementById('pmx-error-detail');
  const detWrap = document.getElementById('pmx-error-details-wrap');
  if (detail) {
    detEl.textContent = typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2);
    detWrap.style.display = '';
    detWrap.open = true;
  } else {
    detWrap.style.display = 'none';
  }
  modal.classList.add('open');
}
function closeErrorModal() {
  const m = document.getElementById('pmx-error-modal');
  if (m) m.classList.remove('open');
}
function copyErrorDetail() {
  const t = (document.getElementById('pmx-error-title')?.textContent || '') + '\n\n'
          + (document.getElementById('pmx-error-msg')?.textContent || '') + '\n\n'
          + (document.getElementById('pmx-error-detail')?.textContent || '');
  navigator.clipboard?.writeText(t);
  showToast('Dettaglio copiato', 'success');
}

// ---------- Tasks log panel (bottom-right, Proxmox-style) ----------

let TASKS_PANEL_OPEN = false;
let TASKS_POLL_TIMER = null;

function ensureTasksPanel() {
  if (document.getElementById('pmx-tasks-panel')) return;
  const el = document.createElement('div');
  el.id = 'pmx-tasks-panel';
  el.className = 'pmx-tasks-panel';
  el.innerHTML = `
    <button class="pmx-tasks-fab" id="pmx-tasks-fab" onclick="toggleTasksPanel()" title="Tasks / Cluster log">
      <span class="material-symbols-rounded">receipt_long</span>
      <span id="pmx-tasks-badge" class="pmx-tasks-badge hidden">0</span>
    </button>
    <div class="pmx-tasks-window hidden" id="pmx-tasks-window">
      <div class="pmx-tasks-header">
        <span class="material-symbols-rounded" style="font-size:16px;color:var(--accent)">receipt_long</span>
        <span style="flex:1;font-size:12.5px;font-weight:700">Tasks / Cluster log</span>
        <button class="pmx-tasks-icon" onclick="loadTasks(true)" title="Aggiorna">
          <span class="material-symbols-rounded" style="font-size:14px">refresh</span>
        </button>
        <button class="pmx-tasks-icon" onclick="toggleTasksPanel()" title="Chiudi">
          <span class="material-symbols-rounded" style="font-size:14px">close</span>
        </button>
      </div>
      <div class="pmx-tasks-list" id="pmx-tasks-list">
        <div style="padding:16px;text-align:center;color:var(--text-dim);font-size:11px">Caricamento…</div>
      </div>
    </div>`;
  document.body.appendChild(el);
  loadTasks(false);
  // Auto-poll every 5s when running tasks exist (otherwise every 30s)
  TASKS_POLL_TIMER = setInterval(() => loadTasks(false), 5000);
}

function toggleTasksPanel() {
  ensureTasksPanel();
  TASKS_PANEL_OPEN = !TASKS_PANEL_OPEN;
  document.getElementById('pmx-tasks-window').classList.toggle('hidden', !TASKS_PANEL_OPEN);
  if (TASKS_PANEL_OPEN) loadTasks(true);
}

async function loadTasks(force) {
  ensureTasksPanel();
  let tasks = [];
  try {
    if (typeof tasksApi !== 'undefined') tasks = await tasksApi.list(false);
  } catch { /* silent */ }
  const list = document.getElementById('pmx-tasks-list');
  const badge = document.getElementById('pmx-tasks-badge');
  if (!list) return;
  const running = tasks.filter(t => t.status === 'running' || t.status === 'pending');
  if (running.length) {
    badge.textContent = running.length;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
  if (!tasks.length) {
    list.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-dim);font-size:11px">Nessun task recente.</div>';
    return;
  }
  list.innerHTML = tasks.slice(0, 30).map(t => {
    const icon = t.status === 'running' ? 'progress_activity'
              : t.status === 'success' ? 'check_circle'
              : t.status === 'error'   ? 'error'
              : 'schedule';
    const color = t.status === 'running' ? 'var(--info)'
                : t.status === 'success' ? 'var(--success)'
                : t.status === 'error'   ? 'var(--danger)'
                : 'var(--text-muted)';
    const spin = t.status === 'running' ? 'pmx-spin' : '';
    const when = t.updated_at ? new Date(t.updated_at).toLocaleTimeString() : '';
    return `<div class="pmx-task-row">
      <span class="material-symbols-rounded ${spin}" style="color:${color};font-size:16px;flex-shrink:0">${icon}</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtmlS(t.kind || 'task')} #${escapeHtmlS(t.vmid || '')}</div>
        <div style="font-size:10.5px;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtmlS(t.message || (t.source_node + '→' + t.target_node))}</div>
      </div>
      <span style="font-size:10px;color:var(--text-dim);font-family:var(--mono);flex-shrink:0">${when}</span>
    </div>`;
  }).join('');
}

function escapeHtmlS(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

// Auto-mount the tasks panel after DOM ready
document.addEventListener('DOMContentLoaded', () => { ensureTasksPanel(); });

// ---------- Active credential ----------

async function ensureActiveCred() {
  let id = getActiveCred();
  const creds = await credsApi.list();
  if (!creds.length) return null;
  const exists = creds.find(c => c.id === id);
  if (!exists) { id = creds[0].id; setActiveCred(id); }
  return id;
}
