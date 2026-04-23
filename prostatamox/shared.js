// shared.js — Navigation helpers, mock auth, sidebar logic

const MOCK_USERS = [
  { username: 'admin',  password: 'admin123',  role: 'Admin Local',  level: 'admin',  name: 'Admin Local' },
  { username: 'senior', password: 'senior123', role: 'Admin Senior', level: 'senior', name: 'Senior Admin' },
  { username: 'junior', password: 'junior123', role: 'Admin Junior', level: 'junior', name: 'Junior Admin' },
];

const PAGES = {
  dashboard:  'dashboard.html',
  nodes:      'node-detail.html',
  vmdetail:   'vm-detail.html',
  migration:  'migration.html',
  backup:     'backup.html',
  users:      'users.html',
  login:      'login.html',
};

function getSession() {
  try { return JSON.parse(sessionStorage.getItem('pmx_session')); } catch { return null; }
}
function setSession(user) {
  sessionStorage.setItem('pmx_session', JSON.stringify(user));
}
function clearSession() {
  sessionStorage.removeItem('pmx_session');
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
  senior: ['dashboard','nodes','vmdetail','migration','backup','start','stop','shutdown','reboot','clone','view_all'],
  junior: ['dashboard','nodes','vmdetail','view_all'],
};
function can(session, action) {
  if (!session) return false;
  return (PERMISSIONS[session.level] || []).includes(action);
}

// Mock Proxmox data
const MOCK_DATA = {
  nodes: [
    { id: 'pve1', name: 'pve1', status: 'running', cpu: 42, mem: 67, disk: 55, uptime: '14d 3h', vms: 8, cts: 5, maxcpu: 32, maxmem: 128 },
    { id: 'pve2', name: 'pve2', status: 'running', cpu: 28, mem: 45, disk: 38, uptime: '22d 7h', vms: 6, cts: 3, maxcpu: 16, maxmem: 64  },
    { id: 'pve3', name: 'pve3', status: 'stopped', cpu: 0,  mem: 0,  disk: 72, uptime: '-',      vms: 4, cts: 2, maxcpu: 16, maxmem: 32  },
  ],
  clusters: [
    { id: 'cluster1', name: 'prod-cluster', nodes: ['pve1','pve2'], status: 'ok' },
    { id: 'cluster2', name: 'dev-cluster',  nodes: ['pve3'],        status: 'degraded' },
  ],
  backupServers: [
    { id: 'pbs1', name: 'pbs-main', status: 'running', diskTotal: 20480, diskUsed: 11264 },
    { id: 'pbs2', name: 'pbs-dr',   status: 'running', diskTotal: 10240, diskUsed: 2048  },
  ],
  vms: [
    { id: 100, name: 'web-server-01',  node: 'pve1', type: 'vm', status: 'running', cpu: 12, mem: 34, disk: 20, os: 'Ubuntu 22.04' },
    { id: 101, name: 'db-primary',     node: 'pve1', type: 'vm', status: 'running', cpu: 55, mem: 72, disk: 80, os: 'Debian 12' },
    { id: 102, name: 'lb-nginx',       node: 'pve1', type: 'vm', status: 'running', cpu: 8,  mem: 20, disk: 10, os: 'Alpine 3.18' },
    { id: 103, name: 'mail-server',    node: 'pve2', type: 'vm', status: 'stopped', cpu: 0,  mem: 0,  disk: 40, os: 'Ubuntu 20.04' },
    { id: 104, name: 'monitoring',     node: 'pve2', type: 'vm', status: 'running', cpu: 22, mem: 48, disk: 30, os: 'Debian 12' },
    { id: 200, name: 'nginx-ct',       node: 'pve1', type: 'ct', status: 'running', cpu: 4,  mem: 15, disk: 5,  os: 'Alpine' },
    { id: 201, name: 'redis-ct',       node: 'pve1', type: 'ct', status: 'running', cpu: 7,  mem: 22, disk: 8,  os: 'Debian' },
    { id: 202, name: 'dns-ct',         node: 'pve2', type: 'ct', status: 'running', cpu: 2,  mem: 8,  disk: 3,  os: 'Alpine' },
    { id: 203, name: 'proxy-ct',       node: 'pve3', type: 'ct', status: 'stopped', cpu: 0,  mem: 0,  disk: 6,  os: 'Ubuntu' },
  ],
  snapshots: {
    100: [
      { id: 'snap1', name: 'pre-update',    date: '2024-05-10 14:32', desc: 'Before nginx upgrade to 1.25' },
      { id: 'snap2', name: 'stable-v2',     date: '2024-04-28 09:15', desc: 'Stable production state v2' },
    ],
    101: [
      { id: 'snap3', name: 'db-backup-apr', date: '2024-04-30 03:00', desc: 'Monthly auto-snapshot April' },
    ],
  },
};

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
