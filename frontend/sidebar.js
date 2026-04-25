// sidebar.js — Renders the sidebar + topbar for every app page.

async function buildSidebar(activePage) {
  const session = requireAuth();
  if (!session) return;
  renderTopbar(session);
  renderSidebarShell(activePage, session);
  await ensureClusterData();          // populates CLUSTER_DATA (active) + ALL_CLUSTERS
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
  const infraOpen = localStorage.getItem('pmx_infra_open') !== '0';
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

      <div class="nav-section-title" id="infra-header" style="margin-top:8px;cursor:pointer;user-select:none;display:flex;align-items:center;gap:6px" onclick="toggleInfra()">
        <span class="material-symbols-rounded" id="infra-arrow" style="font-size:14px;transition:transform .15s;${infraOpen ? '' : 'transform:rotate(-90deg)'}">expand_more</span>
        <span>Infrastruttura</span>
      </div>
      <div id="sidebar-tree" class="${infraOpen ? '' : 'hidden'}">
        <div style="padding:8px 16px;color:var(--text-dim);font-size:12px">Caricamento...</div>
      </div>
    </nav>
    <div class="resize-handle"></div>
  `;
  const shell = document.getElementById('app-shell');
  initSidebarResize(document.getElementById('sidebar'), shell);
  initSidebarToggle(shell);
}

function toggleInfra() {
  const tree = document.getElementById('sidebar-tree');
  const arrow = document.getElementById('infra-arrow');
  if (!tree) return;
  tree.classList.toggle('hidden');
  const open = !tree.classList.contains('hidden');
  if (arrow) arrow.style.transform = open ? '' : 'rotate(-90deg)';
  localStorage.setItem('pmx_infra_open', open ? '1' : '0');
}

function renderSidebarTree(activePage, session) {
  const el = document.getElementById('sidebar-tree');
  if (!el) return;
  const all = ALL_CLUSTERS || [];
  const activeId = getActiveCred();

  if (!all.length) {
    el.innerHTML = `<div style="padding:12px 16px;color:var(--text-dim);font-size:12px">
      Nessun server configurato.<br>
      <a href="servers.html" style="color:var(--accent)">Configura server →</a>
    </div>`;
    return;
  }

  let html = '';

  all.forEach((server, si) => {
    const sid = `tree-srv-${si}`;
    const isActive = server.cred_id === activeId;
    const dotColor = server.online ? 'var(--success)' : 'var(--danger)';
    const headerStyle = isActive ? 'background:var(--bg-hover);border-left:2px solid var(--accent)' : '';
    const data = server.tree;
    const totalVms = (data.vms || []).length;

    html += `
      <div class="tree-item" style="cursor:pointer;user-select:none;${headerStyle}" onclick="toggleTree('${sid}'); selectActiveCred(${server.cred_id})">
        <span class="tree-expand" id="${sid}-arrow"><span class="material-symbols-rounded" style="font-size:14px;transition:transform .15s">expand_more</span></span>
        <span class="material-symbols-rounded ti-icon" style="color:${dotColor}">dns</span>
        <span class="ti-label" title="${escapeHtml(server.host)}">${escapeHtml(server.cred_name)}</span>
        <span class="ti-badge">${server.online ? totalVms : 'off'}</span>
      </div>
      <div id="${sid}" class="tree-cluster-children">`;

    if (!server.online) {
      html += `<div class="tree-item l1" style="color:var(--text-dim);font-size:11px;font-style:italic">
        <span class="tree-expand"></span>
        <span class="material-symbols-rounded ti-icon" style="color:var(--danger);font-size:14px">cloud_off</span>
        <span class="ti-label">Server offline</span>
      </div>`;
    } else {
      // Native PVE cluster (if any) is shown as a sub-header
      (data.clusters || []).forEach((cluster, ci) => {
        const cid = `${sid}-cl-${ci}`;
        const clusterNodes = data.nodes.filter(n => cluster.nodes.includes(n.id));
        html += `
          <div class="tree-item l1" style="cursor:pointer;user-select:none" onclick="event.stopPropagation();toggleTree('${cid}')">
            <span class="tree-expand" id="${cid}-arrow"><span class="material-symbols-rounded" style="font-size:14px;transition:transform .15s">expand_more</span></span>
            <span class="material-symbols-rounded ti-icon" style="color:var(--info)">hub</span>
            <span class="ti-label">${escapeHtml(cluster.name)}</span>
            <span class="ti-badge">${clusterNodes.length}</span>
          </div>
          <div id="${cid}" class="tree-node-children">`;
        clusterNodes.forEach((node, ni) => {
          html += renderNodeBranch(`${cid}-nd-${ni}`, node, data, server.cred_id, 'l2');
        });
        html += `</div>`;
      });

      // Standalone nodes (not in any cluster)
      const clusterNodeIds = new Set((data.clusters || []).flatMap(c => c.nodes));
      const standaloneNodes = (data.nodes || []).filter(n => !clusterNodeIds.has(n.id));
      standaloneNodes.forEach((node, ni) => {
        html += renderNodeBranch(`${sid}-sa-${ni}`, node, data, server.cred_id, 'l1');
      });
    }

    html += `</div>`;
  });

  el.innerHTML = html;
}

function renderNodeBranch(nid, node, data, credId, levelClass) {
  const nodeVMs = data.vms.filter(v => v.node === node.id);
  let html = `
    <div class="tree-item ${levelClass}" style="cursor:pointer;user-select:none" onclick="event.stopPropagation();toggleTree('${nid}')">
      <span class="tree-expand" id="${nid}-arrow"><span class="material-symbols-rounded" style="font-size:14px;transition:transform .15s">expand_more</span></span>
      <span class="material-symbols-rounded ti-icon" style="color:${node.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">storage</span>
      <span class="ti-label"><a href="node-detail.html?cred=${credId}&id=${encodeURIComponent(node.id)}" style="color:inherit;text-decoration:none" onclick="event.stopPropagation();selectActiveCred(${credId})">${escapeHtml(node.name)}</a></span>
      <span class="ti-badge">${nodeVMs.length}</span>
    </div>
    <div id="${nid}" class="tree-node-children">`;
  nodeVMs.forEach(vm => {
    html += `<a href="vm-detail.html?cred=${credId}&id=${vm.id}" class="tree-item ${levelClass === 'l1' ? 'l2' : 'l3'}" onclick="event.stopPropagation();selectActiveCred(${credId})">
      <span class="tree-expand"></span>
      <span class="material-symbols-rounded ti-icon" style="color:${vm.status === 'running' ? 'var(--success)' : 'var(--text-dim)'}">${vm.type === 'vm' ? 'computer' : 'deployed_code'}</span>
      <span class="ti-label">${escapeHtml(vm.name)}</span>
      <span class="ti-badge">${vm.id}</span>
    </a>`;
  });
  html += `</div>`;
  return html;
}

function selectActiveCred(credId) {
  if (getActiveCred() !== credId) {
    setActiveCred(credId);
    // Force a clean data refresh on next page load
    CLUSTER_DATA = null;
  }
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
