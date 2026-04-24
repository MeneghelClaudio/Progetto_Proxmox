// sidebar.js — Renders the sidebar + topbar for every app page.

async function buildSidebar(activePage) {
  const session = requireAuth();
  if (!session) return;
  renderTopbar(session);
  renderSidebarShell(activePage, session);
  await ensureClusterData();
  renderSidebarTree(activePage, session);
}

function renderTopbar(session) {
  const tb = document.getElementById('topbar');
  if (!tb) return;
  tb.innerHTML = `
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
    </div>
    <div class="topbar-user" id="topbar-user" onclick="logout()" title="Logout"></div>
  `;
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
      <a href="iso-upload.html" class="nav-item${activePage === 'isoupload' ? ' active' : ''}">
        <span class="material-symbols-rounded">upload_file</span>
        <span class="nav-label">ISO / Immagini</span>
      </a>
      <a href="servers.html" class="nav-item${activePage === 'servers' ? ' active' : ''}">
        <span class="material-symbols-rounded">dns</span>
        <span class="nav-label">Server Proxmox</span>
      </a>
      ${can(session, 'manage_cluster') ? `<a href="cluster.html" class="nav-item${activePage === 'cluster' ? ' active' : ''}">
        <span class="material-symbols-rounded">hub</span>
        <span class="nav-label">Gestione Cluster</span>
      </a>` : ''}
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
    el.innerHTML = `<div style="padding:12px 16px;color:var(--text-dim);font-size:12px">
      Nessun nodo disponibile.<br>
      <a href="servers.html" style="color:var(--accent)">Configura server →</a>
    </div>`;
    return;
  }

  let html = '';

  // Cluster con nodi espandibili
  data.clusters.forEach((cluster, ci) => {
    const cid = `tree-cl-${ci}`;
    const clusterNodes = data.nodes.filter(n => cluster.nodes.includes(n.id));
    html += `
      <div class="tree-item" style="cursor:pointer;user-select:none" onclick="toggleTree('${cid}')">
        <span class="tree-expand" id="${cid}-arrow"><span class="material-symbols-rounded" style="font-size:14px;transition:transform .15s">expand_more</span></span>
        <span class="material-symbols-rounded ti-icon" style="color:var(--info)">hub</span>
        <span class="ti-label">${escapeHtml(cluster.name)}</span>
        <span class="ti-badge">${clusterNodes.length}</span>
      </div>
      <div id="${cid}" class="tree-cluster-children">`;
    clusterNodes.forEach((node, ni) => {
      const nid = `tree-nd-${ci}-${ni}`;
      const nodeVMs = data.vms.filter(v => v.node === node.id);
      html += `
        <div class="tree-item l1" style="cursor:pointer;user-select:none" onclick="event.stopPropagation();toggleTree('${nid}')">
          <span class="tree-expand" id="${nid}-arrow"><span class="material-symbols-rounded" style="font-size:14px;transition:transform .15s">expand_more</span></span>
          <span class="material-symbols-rounded ti-icon" style="color:${node.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">storage</span>
          <span class="ti-label"><a href="node-detail.html?id=${node.id}" style="color:inherit;text-decoration:none" onclick="event.stopPropagation()">${escapeHtml(node.name)}</a></span>
          <span class="ti-badge">${nodeVMs.length}</span>
        </div>
        <div id="${nid}" class="tree-node-children">`;
      nodeVMs.forEach(vm => {
        html += `<a href="vm-detail.html?id=${vm.id}" class="tree-item l2" onclick="event.stopPropagation()">
          <span class="tree-expand"></span>
          <span class="material-symbols-rounded ti-icon" style="color:${vm.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">${vm.type === 'vm' ? 'computer' : 'deployed_code'}</span>
          <span class="ti-label">${escapeHtml(vm.name)}</span>
          <span class="ti-badge">${vm.id}</span>
        </a>`;
      });
      html += `</div>`;
    });
    html += `</div>`;
  });

  // Nodi standalone (non in cluster)
  const clusterNodeIds = new Set(data.clusters.flatMap(c => c.nodes));
  const standaloneNodes = data.nodes.filter(n => !clusterNodeIds.has(n.id));
  if (standaloneNodes.length) {
    html += `<div class="nav-section-title" style="padding-top:6px">Standalone</div>`;
    standaloneNodes.forEach((node, ni) => {
      const nid = `tree-sa-${ni}`;
      const nodeVMs = data.vms.filter(v => v.node === node.id);
      if (nodeVMs.length) {
        html += `
          <div class="tree-item" style="cursor:pointer;user-select:none" onclick="toggleTree('${nid}')">
            <span class="tree-expand" id="${nid}-arrow"><span class="material-symbols-rounded" style="font-size:14px;transition:transform .15s">expand_more</span></span>
            <span class="material-symbols-rounded ti-icon" style="color:${node.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">storage</span>
            <span class="ti-label"><a href="node-detail.html?id=${node.id}" style="color:inherit;text-decoration:none" onclick="event.stopPropagation()">${escapeHtml(node.name)}</a></span>
            <span class="ti-badge">${nodeVMs.length}</span>
          </div>
          <div id="${nid}" class="tree-node-children">`;
        nodeVMs.forEach(vm => {
          html += `<a href="vm-detail.html?id=${vm.id}" class="tree-item l2">
            <span class="tree-expand"></span>
            <span class="material-symbols-rounded ti-icon" style="color:${vm.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">${vm.type === 'vm' ? 'computer' : 'deployed_code'}</span>
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

  // Backup storage
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

function toggleTree(id) {
  const el = document.getElementById(id);
  const arrow = document.querySelector(`#${id}-arrow .material-symbols-rounded`);
  if (!el) return;
  el.classList.toggle('hidden');
  if (arrow) arrow.style.transform = el.classList.contains('hidden') ? 'rotate(-90deg)' : '';
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}
