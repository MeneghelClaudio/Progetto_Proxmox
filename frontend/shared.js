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

let CLUSTER_DATA = null;
let CLUSTER_RAW  = null;

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

async function ensureClusterData() {
  if (!CLUSTER_DATA) await refreshClusterData();
  return CLUSTER_DATA;
}

// ---------- Active credential ----------

async function ensureActiveCred() {
  let id = getActiveCred();
  const creds = await credsApi.list();
  if (!creds.length) return null;
  const exists = creds.find(c => c.id === id);
  if (!exists) { id = creds[0].id; setActiveCred(id); }
  return id;
}
