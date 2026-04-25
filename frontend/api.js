// api.js — Real backend API client (JWT bearer over fetch)
// Replaces the MOCK_DATA layer of prostatamox with live calls.

const API_BASE = '';  // same origin, nginx proxies /api/ to backend

// ---------- Token storage ----------
// We keep session info in localStorage so it survives refreshes.
// Key: pmx_session -> { token, username, full_name, email, role, is_admin }

function getSession() {
  try { return JSON.parse(localStorage.getItem('pmx_session')); } catch { return null; }
}
function setSession(sess) {
  localStorage.setItem('pmx_session', JSON.stringify(sess));
}
function clearSession() {
  localStorage.removeItem('pmx_session');
  localStorage.removeItem('pmx_active_cred');
}
function getToken() {
  const s = getSession();
  return s?.token || null;
}

// ---------- Active credential (which Proxmox cluster) ----------

function getActiveCred() {
  const v = localStorage.getItem('pmx_active_cred');
  return v ? parseInt(v) : null;
}
function setActiveCred(id) {
  if (id == null) localStorage.removeItem('pmx_active_cred');
  else localStorage.setItem('pmx_active_cred', String(id));
}

// ---------- HTTP helpers ----------

async function apiRequest(path, { method = 'GET', body = null, form = false } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers['Authorization'] = 'Bearer ' + token;

  let bodyToSend = null;
  if (form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    bodyToSend = new URLSearchParams(body).toString();
  } else if (body !== null) {
    headers['Content-Type'] = 'application/json';
    bodyToSend = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(API_BASE + path, { method, headers, body: bodyToSend });
  } catch (e) {
    throw new Error('Errore di rete: ' + e.message);
  }

  if (res.status === 401) {
    clearSession();
    if (!location.pathname.endsWith('login.html')) {
      location.href = 'login.html';
    }
    throw new Error('Sessione scaduta');
  }

  if (res.status === 204) return null;

  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await res.json() : await res.text();

  if (!res.ok) {
    let msg, detail;
    if (data && typeof data === 'object') {
      // FastAPI/Proxmox style: { detail: "..." } oppure { detail: [{ msg: "..." }] }
      if (Array.isArray(data.detail)) {
        msg = data.detail.map(d => d.msg || JSON.stringify(d)).join('; ');
        detail = JSON.stringify(data.detail, null, 2);
      } else {
        msg = data.detail || data.message || `HTTP ${res.status}`;
        detail = data.proxmox_error || data.stderr || null;
      }
    } else {
      msg = typeof data === 'string' ? data : `HTTP ${res.status}`;
      detail = null;
    }
    const err = new Error(msg);
    err.detail = detail;
    err.status = res.status;
    throw err;
  }
  return data;
}

// ---------- Auth API ----------

const authApi = {
  login: async (username, password) => {
    const data = await apiRequest('/api/auth/login', {
      method: 'POST',
      form: true,
      body: { username, password },
    });
    const sess = {
      token:     data.access_token,
      username:  data.username,
      full_name: data.full_name || data.username,
      email:     data.email || '',
      role:      data.role,
      is_admin:  data.is_admin,
      // Derived fields for UI compatibility with prostatamox
      name:      data.full_name || data.username,
      level:     data.role,                                  // admin | senior | junior
      role_label: roleLabel(data.role),
    };
    setSession(sess);
    return sess;
  },
  me: () => apiRequest('/api/auth/me'),
};

function roleLabel(role) {
  return { admin: 'Admin Local', senior: 'Admin Senior', junior: 'Admin Junior' }[role] || role;
}

// ---------- Users API (admin) ----------

const usersApi = {
  list:   ()         => apiRequest('/api/users'),
  create: (payload)  => apiRequest('/api/users', { method: 'POST', body: payload }),
  update: (id, patch)=> apiRequest(`/api/users/${id}`, { method: 'PATCH', body: patch }),
  remove: (id)       => apiRequest(`/api/users/${id}`, { method: 'DELETE' }),
};

// ---------- Credentials API (Proxmox servers) ----------

const credsApi = {
  list:   ()           => apiRequest('/api/credentials'),
  create: (payload)    => apiRequest('/api/credentials', { method: 'POST', body: payload }),
  update: (id, patch)  => apiRequest(`/api/credentials/${id}`, { method: 'PATCH', body: patch }),
  remove: (id)         => apiRequest(`/api/credentials/${id}`, { method: 'DELETE' }),
};

// ---------- Cluster / nodes API ----------

const clusterApi = {
  tree:     (credId)                  => apiRequest(`/api/clusters/${credId}/tree`),
  allTrees: ()                        => apiRequest('/api/clusters/all'),
  status:   (credId)                  => apiRequest(`/api/clusters/${credId}/status`),
  node:     (credId, node)            => apiRequest(`/api/clusters/${credId}/nodes/${node}`),
  nodeRrd:  (credId, node, tf='hour') => apiRequest(`/api/clusters/${credId}/nodes/${node}/rrd?timeframe=${tf}`),
  create:   (payload)                 => apiRequest('/api/clusters', { method: 'POST', body: payload }),
  join:     (credId, payload)         => apiRequest(`/api/clusters/${credId}/cluster/join`, { method: 'POST', body: payload }),
  resources:(credId, node)            => apiRequest(`/api/clusters/${credId}/nodes/${node}/resources`),
};

// ---------- Create VM / CT API ----------

const createApi = {
  resources: (credId, node)            => apiRequest(`/api/clusters/${credId}/nodes/${node}/resources`),
  vm:        (credId, node, payload)   => apiRequest(`/api/clusters/${credId}/nodes/${node}/qemu`, { method: 'POST', body: payload }),
  ct:        (credId, node, payload)   => apiRequest(`/api/clusters/${credId}/nodes/${node}/lxc`,  { method: 'POST', body: payload }),
};

// ---------- VM / CT API ----------

const vmsApi = {
  current:  (credId, kind, node, vmid)            => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}`),
  rrd:      (credId, kind, node, vmid, tf='hour') => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/rrd?timeframe=${tf}`),
  start:    (credId, kind, node, vmid)            => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/start`,    { method: 'POST' }),
  stop:     (credId, kind, node, vmid)            => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/stop`,     { method: 'POST' }),
  shutdown: (credId, kind, node, vmid)            => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/shutdown`, { method: 'POST' }),
  reboot:   (credId, kind, node, vmid)            => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/reboot`,   { method: 'POST' }),
  clone:    (credId, kind, node, vmid, payload) => {
    // LXC clone non richiede `full` esplicito; lasciamo che il backend
    // applichi i default appropriati al tipo di storage rilevato.
    return apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/clone`, { method: 'POST', body: payload });
  },
  remove:   (credId, kind, node, vmid, confirmName)=>apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/delete`,   { method: 'POST', body: { confirm_name: confirmName } }),
  migrate:  (credId, kind, node, vmid, payload)   => apiRequest(`/api/clusters/${credId}/vms/${kind}/${node}/${vmid}/migrate`,  { method: 'POST', body: payload }),
};

// ---------- Snapshots / backups API ----------

const snapApi = {
  list:     (credId, kind, node, vmid)              => apiRequest(`/api/clusters/${credId}/snapshots/${kind}/${node}/${vmid}`),
  create:   (credId, kind, node, vmid, payload)     => apiRequest(`/api/clusters/${credId}/snapshots/${kind}/${node}/${vmid}`, { method: 'POST', body: payload }),
  remove:   (credId, kind, node, vmid, snapname)    => apiRequest(`/api/clusters/${credId}/snapshots/${kind}/${node}/${vmid}/${encodeURIComponent(snapname)}`, { method: 'DELETE' }),
  rollback: (credId, kind, node, vmid, snapname)    => apiRequest(`/api/clusters/${credId}/snapshots/${kind}/${node}/${vmid}/${encodeURIComponent(snapname)}/rollback`, { method: 'POST' }),
};

const backupApi = {
  create: (credId, node, vmid, payload)   => apiRequest(`/api/clusters/${credId}/backups/${node}/${vmid}`, { method: 'POST', body: payload }),
  list:   (credId, node, storage, vmid)   => {
    const q = vmid ? `?vmid=${vmid}` : '';
    return apiRequest(`/api/clusters/${credId}/backups/${node}/${storage}${q}`);
  },
};

// ---------- Tasks API ----------

const tasksApi = {
  list:    (active = false)  => apiRequest(`/api/tasks${active ? '?active=true' : ''}`),
  dismiss: (id)              => apiRequest(`/api/tasks/${id}`, { method: 'DELETE' }),
};

// ---------- ISO / Storage content API ----------

const isoApi = {
  // Lista i file ISO/template disponibili su uno storage di un nodo
  list: (credId, node, storage, type = 'iso') =>
    apiRequest(`/api/clusters/${credId}/nodes/${node}/storage/${storage}/content?content=${type}`),
  // Upload ISO: usa FormData (multipart)
  upload: (credId, node, storage, file, onProgress) => {
    return new Promise((resolve, reject) => {
      const token = getToken();
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}/api/clusters/${credId}/nodes/${node}/storage/${storage}/upload`);
      if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);
      xhr.upload.addEventListener('progress', e => {
        if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded / e.total * 100));
      });
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText || 'null'));
        } else {
          let msg = `HTTP ${xhr.status}`;
          try { msg = JSON.parse(xhr.responseText)?.detail || msg; } catch {}
          const err = new Error(msg); err.status = xhr.status; reject(err);
        }
      });
      xhr.addEventListener('error', () => reject(new Error('Errore di rete upload')));
      const fd = new FormData();
      fd.append('file', file);
      fd.append('filename', file.name);
      xhr.send(fd);
    });
  },
};



/**
 * Normalize the /tree payload into the shape the prostatamox UI expected:
 *   { nodes: [{id, name, status, cpu, mem, disk, uptime, vms, cts, maxcpu, maxmem}...],
 *     vms:   [{id, name, node, type: 'vm'|'ct', status, cpu, mem, disk, os}, ...],
 *     clusters: [{id, name, nodes:[], status}],
 *     backupServers: [{id, name, status, diskTotal, diskUsed}] }
 */
function normalizeTree(tree) {
  const nodes = [];
  const vms = [];

  (tree.nodes || []).forEach(n => {
    const maxcpu = n.maxcpu || 0;
    const maxmem = n.maxmem || 0;                        // bytes
    const memUsed = n.mem || 0;                          // bytes
    const cpuPct = Math.round((n.cpu || 0) * 100);
    const memPct = maxmem ? Math.round((memUsed / maxmem) * 100) : 0;
    // disk pct: average of local storages
    let diskUsed = 0, diskTotal = 0;
    (n.storages || []).forEach(s => {
      if (s.used) diskUsed += s.used;
      if (s.total) diskTotal += s.total;
    });
    const diskPct = diskTotal ? Math.round((diskUsed / diskTotal) * 100) : 0;

    nodes.push({
      id: n.node,
      name: n.node,
      status: n.status === 'online' ? 'running' : 'stopped',
      cpu: cpuPct,
      mem: memPct,
      disk: diskPct,
      // Fix 9: dettaglio dischi per nodo
      disks: (n.storages || []).map(s => ({
        name: s.storage || s.id || '?',
        sizeGB: s.total ? Math.round(s.total / (1024 ** 3)) : 0,
        usedGB: s.used  ? Math.round(s.used  / (1024 ** 3)) : 0,
        pct: s.total && s.used ? Math.round(s.used / s.total * 100) : 0,
        type: s.plugintype || 'dir',
        content: s.content || '',
        shared: !!s.shared,
      })),
      diskTotalGB: diskTotal ? Math.round(diskTotal / (1024 ** 3)) : 0,
      diskUsedGB:  diskUsed  ? Math.round(diskUsed  / (1024 ** 3)) : 0,
      uptime: fmtUptime(n.uptime),
      vms: (n.vms || []).length,
      cts: (n.cts || []).length,
      maxcpu: maxcpu,
      maxmem: Math.round(maxmem / (1024 ** 3)),
    });

    (n.vms || []).forEach(v => {
      const vmPct = v.maxmem ? Math.round((v.mem || 0) / v.maxmem * 100) : 0;
      vms.push({
        id: v.vmid,
        name: v.name || `vm-${v.vmid}`,
        node: n.node,
        type: 'vm',
        kind: 'qemu',
        status: v.status || 'stopped',
        cpu: Math.round((v.cpu || 0) * 100),
        mem: vmPct,
        disk: v.maxmem ? Math.round(v.maxmem / (1024 ** 3)) : 0,
        os: '',
      });
    });
    (n.cts || []).forEach(c => {
      const mPct = c.maxmem ? Math.round((c.mem || 0) / c.maxmem * 100) : 0;
      vms.push({
        id: c.vmid,
        name: c.name || `ct-${c.vmid}`,
        node: n.node,
        type: 'ct',
        kind: 'lxc',
        status: c.status || 'stopped',
        cpu: Math.round((c.cpu || 0) * 100),
        mem: mPct,
        disk: c.maxmem ? Math.round(c.maxmem / (1024 ** 3)) : 0,
        os: '',
      });
    });
  });

  const clusters = tree.cluster ? [{
    id: tree.cluster.name || 'cluster',
    name: tree.cluster.name || 'cluster',
    nodes: nodes.map(n => n.id),
    status: tree.cluster.quorate ? 'ok' : 'degraded',
  }] : [];

  const backupServers = (tree.backup_targets || []).map(bt => ({
    id: `${bt.node}/${bt.storage}`,
    name: bt.storage,
    status: 'running',
    diskTotal: bt.total ? Math.round(bt.total / (1024 ** 2)) : 0, // MB
    diskUsed:  bt.used  ? Math.round(bt.used  / (1024 ** 2)) : 0,
  }));

  return { nodes, vms, clusters, backupServers };
}

function fmtUptime(sec) {
  if (!sec) return '-';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  return d ? `${d}d ${h}h` : `${h}h`;
}

// ---------- Permission matrix (client-side duplicate for UX) ----------
// The authoritative gate lives on the backend; this is for hiding buttons.

const PERMISSIONS = {
  admin:  ['dashboard','nodes','vmdetail','migration','backup','users','delete','clone','start','stop','shutdown','reboot','snapshot_create','snapshot_delete','add_server','manage_cluster','view_all'],
  senior: ['dashboard','nodes','vmdetail','migration','backup','start','stop','shutdown','reboot','clone','snapshot_create','add_server','view_all'],
  junior: ['dashboard','nodes','vmdetail','backup','view_all'],
};

function can(session, action) {
  if (!session) return false;
  return (PERMISSIONS[session.level] || []).includes(action);
}

// ---------- Auth guards ----------

function requireAuth() {
  const s = getSession();
  if (!s || !s.token) {
    location.href = 'login.html';
    return null;
  }
  return s;
}

function logout() {
  clearSession();
  location.href = 'login.html';
}
