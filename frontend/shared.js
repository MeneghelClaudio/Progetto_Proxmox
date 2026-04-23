// shared.js — Navigation helpers + real backend auth/api

const PAGES = {
  dashboard:  'dashboard.html',
  nodes:      'node-detail.html',
  vmdetail:   'vm-detail.html',
  migration:  'migration.html',
  backup:     'backup.html',
  users:      'users.html',
  login:      'login.html',
};

const TOKEN_KEY = 'pmx_token';

async function api(path, { method = 'GET', body = null } = {}) {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers['Content-Type'] = 'application/json';

  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401) {
    clearSession();
    window.location.href = 'login.html';
    throw new Error('Sessione scaduta');
  }
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('application/json') ? response.json() : response.text();
}

function getSession() {
  try { return JSON.parse(localStorage.getItem('pmx_session')); } catch { return null; }
}
function setSession(user) {
  localStorage.setItem('pmx_session', JSON.stringify(user));
}
function clearSession() {
  localStorage.removeItem('pmx_session');
  localStorage.removeItem(TOKEN_KEY);
}
function requireAuth() {
  const s = getSession();
  if (!s) { window.location.href = 'login.html'; return null; }
  return s;
}
function logout() {
  clearSession();
  window.location.href = 'login.html';
}

// Permission matrix
const PERMISSIONS = {
  admin:  ['dashboard','nodes','vmdetail','migration','backup','users','delete','clone','start','stop','shutdown','reboot','add_server','manage_cluster','view_all'],
  senior: ['dashboard','nodes','vmdetail','migration','backup','clone','start','stop','shutdown','reboot','view_all'],
  junior: ['dashboard','nodes','vmdetail','view_all'],
};
function can(session, action) {
  if (!session) return false;
  return (PERMISSIONS[session.level] || []).includes(action);
}

const LIVE_DATA = { currentCredId: null, tree: null };
let MOCK_DATA = { nodes: [], clusters: [], vms: [], backupServers: [], snapshots: {} };

function toLegacyMockData(tree) {
  const nodes = (tree?.nodes || []).map(n => ({
    id: n.node,
    name: n.node,
    status: n.status === 'online' ? 'running' : 'stopped',
    cpu: Math.round((n.cpu || 0) * 100),
    mem: n.maxmem ? Math.round(((n.mem || 0) / n.maxmem) * 100) : 0,
    disk: n.maxdisk ? Math.round(((n.disk || 0) / n.maxdisk) * 100) : 0,
    uptime: n.uptime || '-',
  }));
  const vms = [];
  (tree?.nodes || []).forEach(n => {
    (n.vms || []).forEach(v => vms.push({ id: v.vmid, name: v.name || `vm-${v.vmid}`, node: n.node, type: 'vm', status: v.status || 'stopped' }));
    (n.cts || []).forEach(c => vms.push({ id: c.vmid, name: c.name || `ct-${c.vmid}`, node: n.node, type: 'ct', status: c.status || 'stopped' }));
  });
  const clusters = [{ id: 'c1', name: tree?.cluster?.name || 'cluster', nodes: nodes.map(n => n.id), status: tree?.cluster?.quorate ? 'ok' : 'degraded' }];
  const backupServers = (tree?.backup_targets || []).map((b, i) => ({
    id: `backup-${i}`,
    name: `${b.storage}@${b.node}`,
    status: 'running',
    diskTotal: b.total || 0,
    diskUsed: b.used || 0,
  }));
  return { nodes, clusters, vms, backupServers, snapshots: {} };
}

async function loadTreeData() {
  const creds = await api('/api/credentials');
  if (!creds.length) {
    LIVE_DATA.currentCredId = null;
    LIVE_DATA.tree = null;
    return LIVE_DATA;
  }
  LIVE_DATA.currentCredId = creds[0].id;
  LIVE_DATA.tree = await api(`/api/clusters/${LIVE_DATA.currentCredId}/tree`);
  MOCK_DATA = toLegacyMockData(LIVE_DATA.tree);
  return LIVE_DATA;
}

// Render topbar user info
function renderTopbarUser(session) {
  const el = document.getElementById('topbar-user');
  if (!el || !session) return;
  const initials = session.name.split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase();
  el.innerHTML = `
    <div class="user-avatar">${initials}</div>
    <div class="user-info">
      <span class="user-name">${session.name}</span>
      <span class="user-role">${session.role}</span>
    </div>
    <span class="role-badge ${session.level}">${session.level}</span>
  `;
}

// Toast
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
  toast.innerHTML = `<span class="material-symbols-rounded" style="color:${colors[type]||colors.info};font-size:18px">${icons[type]||'info'}</span><span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// Theme toggle
function initTheme() {
  const saved = localStorage.getItem('pmx_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('pmx_theme', next);
  // Update icon
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) btn.querySelector('span').textContent = next === 'dark' ? 'light_mode' : 'dark_mode';
}
initTheme();

// Sidebar resize
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

// Sidebar toggle
function initSidebarToggle(shellEl) {
  const btn = document.getElementById('sidebar-toggle-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    shellEl.classList.toggle('sidebar-collapsed');
  });
}
