// sidebar.js — Renders shared sidebar + topbar for all app pages

function buildSidebar(activePage) {
  const session = requireAuth();
  if (!session) return;

  const data = LIVE_DATA.tree ? mapTreeToFrontendData(LIVE_DATA.tree) : { clusters: [], nodes: [], vms: [], backupServers: [] };

  const sidebarHTML = `
    <button class="sidebar-toggle" id="sidebar-toggle-btn" title="Toggle sidebar">
      <span class="material-symbols-rounded" style="font-size:20px">menu_open</span>
    </button>
    <nav class="sidebar-nav" id="sidebar-nav">
      <div class="nav-section-title">Navigazione</div>
      <a href="dashboard.html" class="nav-item${activePage==='dashboard'?' active':''}" >
        <span class="material-symbols-rounded">dashboard</span>
        <span class="nav-label">Dashboard</span>
      </a>
      <a href="node-detail.html" class="nav-item${activePage==='nodes'?' active':''}">
        <span class="material-symbols-rounded">memory</span>
        <span class="nav-label">Nodi</span>
      </a>
      <a href="vm-detail.html" class="nav-item${activePage==='vmdetail'?' active':''}">
        <span class="material-symbols-rounded">computer</span>
        <span class="nav-label">VM &amp; Container</span>
      </a>
      ${can(session,'migration') ? `<a href="migration.html" class="nav-item${activePage==='migration'?' active':''}">
        <span class="material-symbols-rounded">swap_horiz</span>
        <span class="nav-label">Migrazione</span>
      </a>` : ''}
      <a href="backup.html" class="nav-item${activePage==='backup'?' active':''}">
        <span class="material-symbols-rounded">backup</span>
        <span class="nav-label">Backup &amp; Snapshot</span>
      </a>
      ${can(session,'manage_cluster') ? `<a href="users.html" class="nav-item${activePage==='users'?' active':''}">
        <span class="material-symbols-rounded">manage_accounts</span>
        <span class="nav-label">Utenti &amp; Permessi</span>
      </a>` : ''}

      <div class="nav-section-title" style="margin-top:8px">Infrastruttura</div>
      ${buildTreeHTML(data, session)}
    </nav>
    <div class="resize-handle"></div>
  `;

  const topbarHTML = `
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
        <span class="material-symbols-rounded" style="font-size:20px">${(localStorage.getItem('pmx_theme')||'dark')==='dark'?'light_mode':'dark_mode'}</span>
      </button>
      <button class="topbar-btn" title="Notifiche">
        <span class="material-symbols-rounded" style="font-size:20px">notifications</span>
      </button>
    </div>
    <div class="topbar-user" id="topbar-user" onclick="logout()" title="Logout"></div>
  `;

  document.getElementById('topbar').innerHTML = topbarHTML;
  document.getElementById('sidebar').innerHTML = sidebarHTML;

  renderTopbarUser(session);

  const shell = document.getElementById('app-shell');
  initSidebarResize(document.getElementById('sidebar'), shell);
  initSidebarToggle(shell);
}

function mapTreeToFrontendData(tree) {
  const clusterName = tree?.cluster?.name || 'cluster';
  const nodes = (tree?.nodes || []).map(n => ({
    id: n.node,
    name: n.node,
    status: n.status === 'online' ? 'running' : 'stopped',
  }));
  const vms = [];
  (tree?.nodes || []).forEach(n => {
    (n.vms || []).forEach(v => vms.push({ id: v.vmid, name: v.name || `vm-${v.vmid}`, node: n.node, type: 'vm', status: v.status || 'stopped' }));
    (n.cts || []).forEach(c => vms.push({ id: c.vmid, name: c.name || `ct-${c.vmid}`, node: n.node, type: 'ct', status: c.status || 'stopped' }));
  });
  const backupServers = (tree?.backup_targets || []).map((b, i) => ({ id: `b${i}`, name: `${b.storage}@${b.node}` }));
  return {
    clusters: [{ id: 'c1', name: clusterName, nodes: nodes.map(n => n.id), status: tree?.cluster?.quorate ? 'ok' : 'degraded' }],
    nodes,
    vms,
    backupServers,
  };
}

function buildTreeHTML(data, session) {
  let html = '';
  data.clusters.forEach(cluster => {
    html += `<div class="tree-item" onclick="this.nextElementSibling.classList.toggle('hidden')">
      <span class="tree-expand"><span class="material-symbols-rounded" style="font-size:14px">expand_more</span></span>
      <span class="material-symbols-rounded ti-icon" style="color:var(--info)">hub</span>
      <span class="ti-label">${cluster.name}</span>
      <span class="ti-badge">${cluster.nodes.length}</span>
    </div>`;
    const clusterNodes = data.nodes.filter(n => cluster.nodes.includes(n.id));
    html += `<div class="tree-cluster-children">`;
    clusterNodes.forEach(node => {
      const nodeVMs = data.vms.filter(v => v.node === node.id);
      html += `<div class="tree-item l1" onclick="(e=>{e.stopPropagation();this.nextElementSibling.classList.toggle('hidden')})(event)">
        <span class="tree-expand"><span class="material-symbols-rounded" style="font-size:14px">expand_more</span></span>
        <span class="material-symbols-rounded ti-icon" style="color:${node.status==='running'?'var(--success)':'var(--text-dim)'}">storage</span>
        <span class="ti-label">${node.name}</span>
        <span class="ti-badge">${nodeVMs.length}</span>
      </div>`;
      html += `<div class="tree-node-children">`;
      nodeVMs.forEach(vm => {
        html += `<a href="vm-detail.html?id=${vm.id}" class="tree-item l2">
          <span class="tree-expand"></span>
          <span class="material-symbols-rounded ti-icon" style="color:${vm.status==='running'?'var(--success)':'var(--text-dim)'}">
            ${vm.type==='vm'?'computer':'deployed_code'}
          </span>
          <span class="ti-label">${vm.name}</span>
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
    standaloneNodes.forEach(node => {
      html += `<a href="node-detail.html?id=${node.id}" class="tree-item">
        <span class="material-symbols-rounded ti-icon" style="color:${node.status==='running'?'var(--success)':'var(--text-dim)'}">storage</span>
        <span class="ti-label">${node.name}</span>
      </a>`;
    });
  }

  // Backup servers
  html += `<div class="nav-section-title" style="margin-top:8px">Backup Server</div>`;
  data.backupServers.forEach(bs => {
    html += `<div class="tree-item">
      <span class="material-symbols-rounded ti-icon" style="color:var(--warning)">backup</span>
      <span class="ti-label">${bs.name}</span>
    </div>`;
  });

  return html;
}
