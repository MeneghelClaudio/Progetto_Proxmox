// shared.js — Common UI helpers (topbar user, toasts, theme, sidebar resize).
// Relies on api.js being loaded first.

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

// ---------- Toast notifications ----------

function showToast(msg, type = 'success') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: 'check_circle', danger: 'error', warning: 'warning', info: 'info' };
  const colors = { success: 'var(--success)', danger: 'var(--danger)', warning: 'var(--warning)', info: 'var(--info)' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span class="material-symbols-rounded" style="color:${colors[type] || colors.info};font-size:18px">${icons[type] || 'info'}</span><span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
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
    e.preventDefault();
    dragging = true;
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
  btn.addEventListener('click', () => {
    shellEl.classList.toggle('sidebar-collapsed');
  });
}

// ---------- Cluster data cache (reused across pages in the same session) ----------
// We keep the last /tree response in memory so multiple widgets on one page
// don't re-fetch. Call refreshClusterData() manually on user action.

let CLUSTER_DATA = null;  // normalized shape { nodes, vms, clusters, backupServers }
let CLUSTER_RAW  = null;  // raw /tree response

async function refreshClusterData() {
  const credId = getActiveCred();
  if (!credId) { CLUSTER_DATA = null; CLUSTER_RAW = null; return null; }
  try {
    const tree = await clusterApi.tree(credId);
    CLUSTER_RAW  = tree;
    CLUSTER_DATA = normalizeTree(tree);
    return CLUSTER_DATA;
  } catch (e) {
    showToast('Errore caricamento cluster: ' + e.message, 'danger');
    CLUSTER_DATA = { nodes: [], vms: [], clusters: [], backupServers: [] };
    CLUSTER_RAW = null;
    return CLUSTER_DATA;
  }
}

async function ensureClusterData() {
  if (!CLUSTER_DATA) await refreshClusterData();
  return CLUSTER_DATA;
}

// ---------- Active credential picker ----------
// If user has multiple Proxmox servers registered, stash the active one.

async function ensureActiveCred() {
  let id = getActiveCred();
  const creds = await credsApi.list();
  if (!creds.length) return null;
  const exists = creds.find(c => c.id === id);
  if (!exists) {
    id = creds[0].id;
    setActiveCred(id);
  }
  return id;
}
