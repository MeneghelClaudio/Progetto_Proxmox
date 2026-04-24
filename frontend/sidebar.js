// sidebar.js — Renders the sidebar + topbar for every app page.
// Uses CLUSTER_DATA (set by refreshClusterData in shared.js).

async function buildSidebar(activePage) {
  const session = requireAuth();
  if (!session) return;

  // Topbar first (instant) — sidebar tree can load async.
  renderTopbar(session);
  renderSidebarShell(activePage, session);

  // Then load real cluster data.
  await ensureClusterData();
  renderSidebarTree(activePage, session);
}

function renderTopbar(session) {
  const html = `
    <div class="topbar-brand">
      <div class="brand-icon"><span class="material-symbols-rounded ms-fill" style="font-size:18px;color:#fff">dns</span></div>
      <span class="brand-name" style="font-size:14px;font-weight:700">ProxMox Manager</span>
    </div>
    <div class="topbar-sep"></div>
    <div class="topbar-actions">
      <button class="topbar-btn" title="Aggiorna" onclick="location.reload()">
        <span class="material-symbols-rounded" style="font-size:20px">refresh</span>
      </button>
      <button class="topbar-btn" id="theme-toggle-btn" title="Cambia tema" onclick="toggleTheme()">
        <span class="material-symbols-rounded" style="font-size:20px">${(localStorage.getItem('pmx_theme') || 'dark') === 'dark' ? 'light_mode' : 'dark_mode'}</span>
      </button>
      <button class="topbar-btn" title="Notifiche">
        <span class="material-symbols-rounded" style="font-size:20px">notifications</span>
      </button>
    </div>
    <div class="topbar-user" id="topbar-user" onclick="logout()" title="Logout"></div>
  `;
  const tb = document.getElementById('topbar');
  if (tb) tb.innerHTML = html;
  renderTopbarUser(session);
}

function renderSidebarShell(activePage, session) {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  sb.innerHTML = `
    <button class="sidebar-toggle" id="sidebar-toggle-btn" title="Toggle sidebar">
      <span class="material-symbols-rounded" style="font-size:20px">menu_open</span>
    </button>
    <nav class="sidebar-nav" id="sidebar-nav">
      <div class="nav-section-title">Navigazione</div>
      <a href="dashboard.html" class="nav-item${activePage === 'dashboard' ? ' active' : ''}">
        <span class="material-symbols-rounded">dashboard</span>
        <span class="nav-label">Dashboard</span>
      </a>
      <a href="node-detail.html" class="nav-item${activePage === 'nodes' ? ' active' : ''}">
        <span class="material-symbols-rounded">memory</span>
        <span class="nav-label">Nodi</span>
      </a>
      <a href="vm-detail.html" class="nav-item${activePage === 'vmdetail' ? ' active' : ''}">
        <span class="material-symbols-rounded">computer</span>
        <span class="nav-label">VM &amp; Container</span>
      </a>
      ${can(session, 'migration') ? `<a href="migration.html" class="nav-item${activePage === 'migration' ? ' active' : ''}">
        <span class="material-symbols-rounded">swap_horiz</span>
        <span class="nav-label">Migrazione</span>
      </a>` : ''}
      <a href="backup.html" class="nav-item${activePage === 'backup' ? ' active' : ''}">
        <span class="material-symbols-rounded">backup</span>
        <span class="nav-label">Backup &amp; Snapshot</span>
      </a>
      <a href="servers.html" class="nav-item${activePage === 'servers' ? ' active' : ''}">
        <span class="material-symbols-rounded">dns</span>
        <span class="nav-label">Server Proxmox</span>
      </a>
      ${can(session, 'manage_cluster') ? `<a href="users.html" class="nav-item${activePage === 'users' ? ' active' : ''}">
        <span class="material-symbols-rounded">manage_accounts</span>
        <span class="nav-label">Utenti &amp; Permessi</span>
      </a>` : ''}

      <div class="nav-section-title" style="margin-top:8px">Infrastruttura</div>
      <div id="sidebar-tree">
        <div style="padding:8px 16px;color:var(--text-dim);font-size:12px">Caricamento...</div>
      </div>
    </nav>
    <div class="resize-handle"></div>
  `;

  const shell = document.getElementById('app-shell');
  initSidebarResize(document.getElementById('sidebar'), shell);
  initSidebarToggle(shell);
}

function renderSidebarTree(activePage, session) {
  const el = document.getElementById('sidebar-tree');
  if (!el) return;
  const data = CLUSTER_DATA;
  if (!data || (!data.nodes.length && !data.clusters.length)) {
    el.innerHTML = `
      <div style="padding:12px 16px;color:var(--text-dim);font-size:12px">
        Nessun server Proxmox configurato.<br>
        <a href="servers.html" style="color:var(--accent)">Aggiungine uno →</a>
      </div>`;
    return;
  }

  let html = '';

  // Fix 7: usa id univoci per toggle espandi/collassa
  data.clusters.forEach((cluster, ci) => {
    const cid = `tree-cl-${ci}`;
    html += `<div class="tree-item" style="cursor:pointer" onclick="document.getElementById('${cid}').classList.toggle('hidden')">
      <span class="tree-expand"><span class="material-symbols-rounded" style="font-size:14px">expand_more</span></span>
      <span class="material-symbols-rounded ti-icon" style="color:var(--info)">hub</span>
      <span class="ti-label">${escapeHtml(cluster.name)}</span>
      <span class="ti-badge">${cluster.nodes.length}</span>
    </div>`;
    const clusterNodes = data.nodes.filter(n => cluster.nodes.includes(n.id));
    html += `<div id="${cid}" class="tree-cluster-children">`;
    clusterNodes.forEach((node, ni) => {
      const nid = `tree-nd-${ci}-${ni}`;
      const nodeVMs = data.vms.filter(v => v.node === node.id);
      html += `<div class="tree-item l1" style="cursor:pointer" onclick="event.stopPropagation();document.getElementById('${nid}').classList.toggle('hidden')">
        <span class="tree-expand"><span class="material-symbols-rounded" style="font-size:14px">expand_more</span></span>
        <span class="material-symbols-rounded ti-icon" style="color:${node.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">storage</span>
        <span class="ti-label">${escapeHtml(node.name)}</span>
        <span class="ti-badge">${nodeVMs.length}</span>
      </div>`;
      html += `<div id="${nid}" class="tree-node-children">`;
      nodeVMs.forEach(vm => {
        html += `<a href="vm-detail.html?id=${vm.id}" class="tree-item l2">
          <span class="tree-expand"></span>
          <span class="material-symbols-rounded ti-icon" style="color:${vm.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">
            ${vm.type === 'vm' ? 'computer' : 'deployed_code'}
          </span>
          <span class="ti-label">${escapeHtml(vm.name)}</span>
          <span class="ti-badge">${vm.id}</span>
        </a>`;
      });
      html += `</div>`;
    });
    html += `</div>`;
  });

  // Standalone nodes
  const clusterNodeIds = data.clusters.flatMap(c => c.nodes);
  const standaloneNodes = data.nodes.filter(n => !clusterNodeIds.includes(n.id));
  if (standaloneNodes.length) {
    html += `<div class="nav-section-title">Nodi standalone</div>`;
    standaloneNodes.forEach((node, ni) => {
      const nid = `tree-sa-${ni}`;
      const nodeVMs = data.vms.filter(v => v.node === node.id);
      if (nodeVMs.length) {
        html += `<div class="tree-item" style="cursor:pointer" onclick="document.getElementById('${nid}').classList.toggle('hidden')">
          <span class="tree-expand"><span class="material-symbols-rounded" style="font-size:14px">expand_more</span></span>
          <span class="material-symbols-rounded ti-icon" style="color:${node.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">storage</span>
          <span class="ti-label">${escapeHtml(node.name)}</span>
          <span class="ti-badge">${nodeVMs.length}</span>
        </div>
        <div id="${nid}" class="tree-node-children">`;
        nodeVMs.forEach(vm => {
          html += `<a href="vm-detail.html?id=${vm.id}" class="tree-item l2">
            <span class="tree-expand"></span>
            <span class="material-symbols-rounded ti-icon" style="color:${vm.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">
              ${vm.type === 'vm' ? 'computer' : 'deployed_code'}
            </span>
            <span class="ti-label">${escapeHtml(vm.name)}</span>
            <span class="ti-badge">${vm.id}</span>
          </a>`;
        });
        html += `</div>`;
      } else {
        html += `<a href="node-detail.html?id=${node.id}" class="tree-item">
          <span class="material-symbols-rounded ti-icon" style="color:${node.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">storage</span>
          <span class="ti-label">${escapeHtml(node.name)}</span>
        </a>`;
      }
    });
  }

  // Backup servers
  if (data.backupServers.length) {
    html += `<div class="nav-section-title" style="margin-top:8px">Backup Storage</div>`;
    data.backupServers.forEach(bs => {
      html += `<div class="tree-item">
        <span class="material-symbols-rounded ti-icon" style="color:var(--warning)">backup</span>
        <span class="ti-label">${escapeHtml(bs.name)}</span>
      </div>`;
    });
  }

  el.innerHTML = html;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}
