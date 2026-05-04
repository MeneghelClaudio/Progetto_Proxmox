// demo-data.js — Demo mode per ProxMox Manager
// Carica PRIMA di api.js in ogni pagina HTML.
// Abilita/disabilita con il tasto "Demo" nella topbar → salva in localStorage → ricarica pagina.

(function () {
  'use strict';

  // ─────────────────────────────────────────
  //  Costanti di dimensione
  // ─────────────────────────────────────────
  const MB = 1024 ** 2;
  const GB = 1024 ** 3;
  const TB = 1024 ** 4;

  // ─────────────────────────────────────────
  //  Stato demo mode
  // ─────────────────────────────────────────
  function isDemoMode() {
    return localStorage.getItem('pmx_demo_mode') === '1';
  }

  window.isDemoMode = isDemoMode;

  window.toggleDemoMode = function () {
    const next = !isDemoMode();
    localStorage.setItem('pmx_demo_mode', next ? '1' : '0');
    if (next) {
      // Imposta credenziale demo attiva se non ne esiste già una reale
      localStorage.setItem('pmx_active_cred', '9001');
    } else {
      // Rimuovi la credenziale demo al disattivare
      if (localStorage.getItem('pmx_active_cred') === '9001' ||
          localStorage.getItem('pmx_active_cred') === '9002') {
        localStorage.removeItem('pmx_active_cred');
      }
    }
    // Invalida cache in-memory (se shared.js è già stato caricato)
    if (typeof ALL_CLUSTERS !== 'undefined') { window.ALL_CLUSTERS = null; }
    if (typeof CLUSTER_DATA !== 'undefined') { window.CLUSTER_DATA = null; }
    if (typeof _allClustersTs !== 'undefined') { window._allClustersTs = 0; }
    location.reload();
  };

  // ─────────────────────────────────────────
  //  CREDENZIALI DEMO
  // ─────────────────────────────────────────
  const DEMO_CREDS = [
    { id: 9001, name: 'Demo Cluster Nord', host: '10.0.1.100', port: 8006 },
    { id: 9002, name: 'Demo Edge Site',    host: '10.0.2.100', port: 8006 },
  ];

  // ─────────────────────────────────────────
  //  ALBERI CLUSTER (formato raw backend, prima di normalizeTree)
  // ─────────────────────────────────────────
  const DEMO_TREE_9001 = {
    cluster: { name: 'demo-cluster-nord', quorate: 1 },
    nodes: [
      {
        node: 'pve-node-01', status: 'online', local: true,
        cpu: 0.42, maxcpu: 32, mem: 34 * GB, maxmem: 64 * GB, uptime: 1296000,
        storages: [
          { storage: 'local',    plugintype: 'dir', used: 48 * GB,   total: 200 * GB, content: 'iso,backup',    shared: false },
          { storage: 'ceph-ssd', plugintype: 'rbd', used: 1.2 * TB,  total: 5 * TB,   content: 'images',        shared: true  },
          { storage: 'pbs-main', plugintype: 'pbs', used: 3.2 * TB,  total: 10 * TB,  content: 'backup',        shared: true  },
        ],
        vms: [
          { vmid: 100, name: 'web-server-01',   status: 'running', cpu: 0.12, mem: 4  * GB, maxmem: 8  * GB },
          { vmid: 101, name: 'db-postgres-01',  status: 'running', cpu: 0.35, mem: 12 * GB, maxmem: 16 * GB },
          { vmid: 102, name: 'monitoring-vm',   status: 'stopped', cpu: 0,    mem: 0,        maxmem: 4  * GB },
        ],
        cts: [
          { vmid: 200, name: 'nginx-proxy',  status: 'running', cpu: 0.08, mem: 512 * MB, maxmem: 1  * GB },
          { vmid: 201, name: 'redis-cache',  status: 'running', cpu: 0.05, mem: 256 * MB, maxmem: 512 * MB },
        ],
      },
      {
        node: 'pve-node-02', status: 'online', local: false,
        cpu: 0.28, maxcpu: 32, mem: 22 * GB, maxmem: 64 * GB, uptime: 1296000,
        storages: [
          { storage: 'local',    plugintype: 'dir', used: 32 * GB,  total: 200 * GB, content: 'iso,backup', shared: false },
          { storage: 'ceph-ssd', plugintype: 'rbd', used: 1.2 * TB, total: 5 * TB,   content: 'images',     shared: true  },
          { storage: 'local-backup', plugintype: 'dir', used: 180 * GB, total: 500 * GB, content: 'backup', shared: false },
        ],
        vms: [
          { vmid: 103, name: 'app-server-01', status: 'running', cpu: 0.18, mem: 6 * GB,  maxmem: 8  * GB },
          { vmid: 104, name: 'ldap-server',   status: 'running', cpu: 0.05, mem: 2 * GB,  maxmem: 4  * GB },
          { vmid: 105, name: 'dev-test-01',   status: 'stopped', cpu: 0,    mem: 0,        maxmem: 8  * GB },
        ],
        cts: [
          { vmid: 202, name: 'prometheus',  status: 'running', cpu: 0.15, mem: 768 * MB, maxmem: 2 * GB },
          { vmid: 203, name: 'grafana',     status: 'running', cpu: 0.06, mem: 512 * MB, maxmem: 1 * GB },
        ],
      },
      {
        node: 'pve-node-03', status: 'online', local: false,
        cpu: 0.15, maxcpu: 16, mem: 12 * GB, maxmem: 32 * GB, uptime: 864000,
        storages: [
          { storage: 'local',    plugintype: 'dir', used: 20 * GB,  total: 100 * GB, content: 'iso,backup', shared: false },
          { storage: 'ceph-ssd', plugintype: 'rbd', used: 1.2 * TB, total: 5 * TB,   content: 'images',     shared: true  },
        ],
        vms: [
          { vmid: 106, name: 'backup-agent', status: 'running', cpu: 0.03, mem: 1 * GB, maxmem: 2 * GB },
          { vmid: 107, name: 'vpn-gateway',  status: 'running', cpu: 0.08, mem: 2 * GB, maxmem: 4 * GB },
        ],
        cts: [
          { vmid: 204, name: 'traefik',  status: 'running', cpu: 0.04, mem: 256 * MB, maxmem: 512 * MB },
          { vmid: 205, name: 'certbot',  status: 'stopped', cpu: 0,    mem: 0,         maxmem: 256 * MB },
        ],
      },
    ],
    backup_targets: [
      { storage: 'pbs-main',     node: 'pve-node-01', total: 10 * TB,   used: 3.2 * TB, shared: true  },
      { storage: 'local-backup', node: 'pve-node-02', total: 500 * GB,  used: 180 * GB, shared: false },
    ],
  };

  const DEMO_TREE_9002 = {
    cluster: null,
    nodes: [
      {
        node: 'pve-edge-01', status: 'online', local: true,
        cpu: 0.55, maxcpu: 8, mem: 6 * GB, maxmem: 16 * GB, uptime: 259200,
        storages: [
          { storage: 'local', plugintype: 'dir', used: 60 * GB, total: 120 * GB, content: 'iso,backup,images', shared: false },
        ],
        vms: [
          { vmid: 300, name: 'edge-gateway', status: 'running', cpu: 0.30, mem: 3 * GB, maxmem: 4 * GB },
          { vmid: 301, name: 'iot-hub',      status: 'running', cpu: 0.20, mem: 2 * GB, maxmem: 4 * GB },
        ],
        cts: [
          { vmid: 400, name: 'mqtt-broker', status: 'running', cpu: 0.10, mem: 512 * MB, maxmem: 1 * GB },
          { vmid: 401, name: 'node-red',    status: 'stopped', cpu: 0,    mem: 0,         maxmem: 512 * MB },
        ],
      },
    ],
    backup_targets: [],
  };

  // ─────────────────────────────────────────
  //  UTENTI DEMO
  // ─────────────────────────────────────────
  const DEMO_USERS = [
    { id: 1, username: 'admin',           full_name: 'Amministratore Sistema', email: 'admin@demo.local',           role: 'admin',  is_admin: true,  created_at: '2024-01-01T00:00:00Z' },
    { id: 2, username: 'mario.rossi',     full_name: 'Mario Rossi',            email: 'mario.rossi@demo.local',     role: 'senior', is_admin: false, created_at: '2024-02-10T10:00:00Z' },
    { id: 3, username: 'anna.verdi',      full_name: 'Anna Verdi',             email: 'anna.verdi@demo.local',      role: 'junior', is_admin: false, created_at: '2024-03-15T09:00:00Z' },
    { id: 4, username: 'luca.ferrari',    full_name: 'Luca Ferrari',           email: 'luca.ferrari@demo.local',    role: 'senior', is_admin: false, created_at: '2024-04-01T14:30:00Z' },
    { id: 5, username: 'giulia.bianchi',  full_name: 'Giulia Bianchi',         email: 'giulia.bianchi@demo.local',  role: 'junior', is_admin: false, created_at: '2024-05-20T08:00:00Z' },
    { id: 6, username: 'roberto.esposito',full_name: 'Roberto Esposito',       email: 'r.esposito@demo.local',      role: 'senior', is_admin: false, created_at: '2024-06-05T11:00:00Z' },
  ];

  // ─────────────────────────────────────────
  //  TASKS DEMO
  // ─────────────────────────────────────────
  const now = Date.now();
  const DEMO_TASKS = [
    { id: 'dt-1', kind: 'migrate',  vmid: '103', source_node: 'pve-node-01', target_node: 'pve-node-02', status: 'success', message: 'Migrazione app-server-01 completata',    updated_at: new Date(now - 3600000).toISOString() },
    { id: 'dt-2', kind: 'backup',   vmid: '100', source_node: 'pve-node-01', target_node: 'pbs-main',    status: 'success', message: 'Backup web-server-01 completato (4.2 GB)', updated_at: new Date(now - 7200000).toISOString() },
    { id: 'dt-3', kind: 'snapshot', vmid: '101', source_node: 'pve-node-01', target_node: 'pve-node-01', status: 'success', message: 'Snapshot creato: pre-update-2025',        updated_at: new Date(now - 10800000).toISOString() },
    { id: 'dt-4', kind: 'start',    vmid: '202', source_node: 'pve-node-02', target_node: 'pve-node-02', status: 'running', message: 'Avvio container prometheus in corso…',     updated_at: new Date(now - 120000).toISOString() },
    { id: 'dt-5', kind: 'backup',   vmid: '104', source_node: 'pve-node-02', target_node: 'pbs-main',    status: 'error',   message: 'Errore: storage pbs-main pieno',           updated_at: new Date(now - 1800000).toISOString() },
    { id: 'dt-6', kind: 'migrate',  vmid: '105', source_node: 'pve-node-02', target_node: 'pve-node-03', status: 'success', message: 'Migrazione live dev-test-01 completata',   updated_at: new Date(now - 86400000).toISOString() },
    { id: 'dt-7', kind: 'clone',    vmid: '100', source_node: 'pve-node-01', target_node: 'pve-node-01', status: 'success', message: 'Clone web-server-02 (VMID 108) creato',    updated_at: new Date(now - 172800000).toISOString() },
  ];

  // ─────────────────────────────────────────
  //  SNAPSHOT DEMO (per qualsiasi VM/CT)
  // ─────────────────────────────────────────
  const DEMO_SNAPSHOTS = [
    { name: 'pre-update-2025',  description: 'Prima aggiornamento sistema OS',   snaptime: Math.floor(now / 1000) - 86400  * 7,  parent: '' },
    { name: 'clean-install',    description: 'Post-installazione pulita',         snaptime: Math.floor(now / 1000) - 86400  * 30, parent: '' },
    { name: 'before-migration', description: 'Snapshot pre-migrazione cluster',   snaptime: Math.floor(now / 1000) - 86400  * 14, parent: 'clean-install' },
  ];

  // ─────────────────────────────────────────
  //  BACKUP DEMO (vzdump / PBS)
  // ─────────────────────────────────────────
  const DEMO_BACKUPS = [
    { volid: 'pbs-main:backup/vm/100/2025-04-01T02:00:00Z',     size: 4.2 * GB,   ctime: Math.floor(now / 1000) - 86400 * 34, notes: 'Backup notturno automatico' },
    { volid: 'pbs-main:backup/vm/101/2025-04-08T02:00:00Z',     size: 8.1 * GB,   ctime: Math.floor(now / 1000) - 86400 * 27, notes: 'Backup settimanale' },
    { volid: 'pbs-main:backup/ct/200/2025-04-15T02:00:00Z',     size: 1.8 * GB,   ctime: Math.floor(now / 1000) - 86400 * 20, notes: 'Backup container nginx' },
    { volid: 'local-backup:backup/ct/202/2025-04-20T03:00:00Z', size: 512 * MB,   ctime: Math.floor(now / 1000) - 86400 * 15, notes: 'Backup monitoring' },
    { volid: 'pbs-main:backup/vm/103/2025-04-25T02:00:00Z',     size: 3.5 * GB,   ctime: Math.floor(now / 1000) - 86400 * 10, notes: 'Prima della migrazione' },
    { volid: 'pbs-main:backup/vm/107/2025-04-28T02:00:00Z',     size: 2.1 * GB,   ctime: Math.floor(now / 1000) - 86400 * 7,  notes: '' },
    { volid: 'pbs-main:backup/vm/100/2025-05-01T02:00:00Z',     size: 4.3 * GB,   ctime: Math.floor(now / 1000) - 86400 * 4,  notes: 'Backup mensile' },
  ];

  // ─────────────────────────────────────────
  //  ISO / TEMPLATE DEMO
  // ─────────────────────────────────────────
  const DEMO_ISOS = [
    { volid: 'local:iso/debian-12.5.0-amd64-netinst.iso',             content: 'iso',    size: 0.7  * GB,  format: 'iso' },
    { volid: 'local:iso/ubuntu-22.04.4-live-server-amd64.iso',        content: 'iso',    size: 2.0  * GB,  format: 'iso' },
    { volid: 'local:iso/alpine-virt-3.19.1-x86_64.iso',               content: 'iso',    size: 60   * MB,  format: 'iso' },
    { volid: 'local:iso/Windows_Server_2022_Datacenter_eval.iso',      content: 'iso',    size: 5.4  * GB,  format: 'iso' },
    { volid: 'local:iso/Rocky-9.3-x86_64-minimal.iso',                content: 'iso',    size: 1.3  * GB,  format: 'iso' },
    { volid: 'local:vztmpl/debian-12-standard_12.5-1_amd64.tar.zst',  content: 'vztmpl', size: 0.3  * GB,  format: 'tgz' },
    { volid: 'local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst', content: 'vztmpl', size: 0.4 * GB, format: 'tgz' },
    { volid: 'local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz', content: 'vztmpl', size: 4   * MB,  format: 'tgz' },
  ];

  // ─────────────────────────────────────────
  //  DETTAGLIO VM (per vm-detail.html)
  // ─────────────────────────────────────────
  function buildVmDetail(vmid) {
    const allVms = [
      ...DEMO_TREE_9001.nodes.flatMap(n => (n.vms || []).map(v => ({ ...v, node: n.node, type: 'vm', kind: 'qemu' }))),
      ...DEMO_TREE_9001.nodes.flatMap(n => (n.cts || []).map(c => ({ ...c, node: n.node, type: 'ct', kind: 'lxc' }))),
      ...DEMO_TREE_9002.nodes.flatMap(n => (n.vms || []).map(v => ({ ...v, node: n.node, type: 'vm', kind: 'qemu' }))),
      ...DEMO_TREE_9002.nodes.flatMap(n => (n.cts || []).map(c => ({ ...c, node: n.node, type: 'ct', kind: 'lxc' }))),
    ];
    const vm = allVms.find(v => v.vmid === parseInt(vmid)) || allVms[0];
    const isVm = vm.kind === 'qemu';
    return {
      vmid: vm.vmid,
      name: vm.name,
      status: vm.status,
      cpu: vm.cpu,
      cpus: isVm ? 4 : 2,
      maxcpu: isVm ? 4 : 2,
      mem: vm.mem,
      maxmem: vm.maxmem,
      disk: 32 * GB,
      maxdisk: 32 * GB,
      uptime: vm.status === 'running' ? 345600 : 0,
      node: vm.node,
      type: vm.type,
      kind: vm.kind,
      pid: vm.status === 'running' ? 12345 : null,
      config: isVm
        ? { cores: 4, sockets: 1, memory: Math.round(vm.maxmem / MB), ostype: 'l26', net0: 'virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0', scsi0: 'ceph-ssd:vm-' + vm.vmid + '-disk-0,size=32G', ide2: 'none,media=cdrom', boot: 'order=scsi0', agent: '1' }
        : { cores: 2, memory: Math.round(vm.maxmem / MB), ostype: 'debian', net0: 'name=eth0,bridge=vmbr0,ip=dhcp', rootfs: 'local:' + vm.vmid + '/rootfs,size=8G', hostname: vm.name },
    };
  }

  // ─────────────────────────────────────────
  //  DETTAGLIO NODO (per node-detail.html)
  // ─────────────────────────────────────────
  function buildNodeDetail(nodeId) {
    const allNodes = [
      ...DEMO_TREE_9001.nodes,
      ...DEMO_TREE_9002.nodes,
    ];
    const n = allNodes.find(x => x.node === nodeId) || DEMO_TREE_9001.nodes[0];
    return {
      ...n,
      version: { version: '8.1.4', release: '1', repoid: 'demo' },
      cpuinfo: { cpus: n.maxcpu, model: 'Intel(R) Xeon(R) Gold 6226R @ 2.90GHz', mhz: '2900', sockets: 2 },
      memory: { total: n.maxmem, used: n.mem, free: n.maxmem - n.mem },
      rootfs: { total: 200 * GB, used: 48 * GB, free: 152 * GB, avail: 152 * GB },
      loadavg: ['1.24', '1.08', '0.95'],
      pveversion: 'pve-manager/8.1.4/b46aac3b42da5d15',
      kversion: '6.5.13-3-pve',
      uptime: n.uptime,
    };
  }

  // ─────────────────────────────────────────
  //  STATUS CLUSTER DEMO
  // ─────────────────────────────────────────
  const DEMO_CLUSTER_STATUS = [
    { type: 'cluster', id: 'cluster',       name: 'demo-cluster-nord', quorate: 1, nodes: 3, version: 5 },
    { type: 'node',    id: 'node/pve-node-01', name: 'pve-node-01', online: 1, local: 1, nodeid: 1, ip: '10.0.1.101' },
    { type: 'node',    id: 'node/pve-node-02', name: 'pve-node-02', online: 1, local: 0, nodeid: 2, ip: '10.0.1.102' },
    { type: 'node',    id: 'node/pve-node-03', name: 'pve-node-03', online: 1, local: 0, nodeid: 3, ip: '10.0.1.103' },
  ];

  // ─────────────────────────────────────────
  //  INTERCETTORE  apiRequest
  // ─────────────────────────────────────────
  window._demoIntercept = function (path, method) {
    if (!isDemoMode()) return null;

    const m = (method || 'GET').toUpperCase();

    // ── Mutations: restituisce sempre successo silenzioso ─────────────────
    // (start, stop, create snapshot, create backup, migrate, ecc.)
    if (m !== 'GET') {
      // Eccezione: login, auth non si intercettano
      if (path.startsWith('/api/auth/')) return null;
      return Promise.resolve({ status: 'ok', taskid: 'UPID:demo-node:' + Date.now().toString(16) + ':demo:' + m });
    }

    // ── GET intercepts ────────────────────────────────────────────────────

    // Credenziali
    if (path === '/api/credentials') return ok(DEMO_CREDS);

    // Tutti i cluster
    if (path === '/api/clusters/all') return ok([
      { cred_id: 9001, cred_name: 'Demo Cluster Nord', host: '10.0.1.100', port: 8006, online: true,  tree: DEMO_TREE_9001, error: null },
      { cred_id: 9002, cred_name: 'Demo Edge Site',    host: '10.0.2.100', port: 8006, online: true,  tree: DEMO_TREE_9002, error: null },
    ]);

    // Revisione (per revision polling)
    if (path === '/api/clusters/revision') return ok({ rev: 42 });

    // Tree singolo cluster
    if (/^\/api\/clusters\/\d+\/tree/.test(path)) {
      const credId = parseInt(path.split('/')[3]);
      return ok(credId === 9002 ? DEMO_TREE_9002 : DEMO_TREE_9001);
    }

    // Status cluster
    if (/^\/api\/clusters\/\d+\/status$/.test(path)) return ok(DEMO_CLUSTER_STATUS);

    // Dettaglio nodo
    if (/^\/api\/clusters\/\d+\/nodes\/[^/]+$/.test(path)) {
      const parts = path.split('/');
      const nodeId = decodeURIComponent(parts[parts.length - 1]);
      return ok(buildNodeDetail(nodeId));
    }

    // RRD nodo (grafici storici) → array vuoto va bene
    if (/\/nodes\/[^/]+\/rrd/.test(path)) return ok([]);

    // Risorse nodo (storages, dischi, ecc.)
    if (/\/nodes\/[^/]+\/resources$/.test(path)) {
      const parts = path.split('/');
      const nodeId = decodeURIComponent(parts[parts.length - 2]);
      const allNodes = [...DEMO_TREE_9001.nodes, ...DEMO_TREE_9002.nodes];
      const n = allNodes.find(x => x.node === nodeId) || DEMO_TREE_9001.nodes[0];
      return ok({
        storages: (n.storages || []).map(s => ({ ...s, id: s.storage, avail: s.total - s.used })),
        nextid: 108,
        isos: DEMO_ISOS.filter(i => i.content === 'iso').map(i => i.volid.split('/').pop()),
        templates: DEMO_ISOS.filter(i => i.content === 'vztmpl').map(i => i.volid.split('/').pop()),
      });
    }

    // ISO / template content
    if (/\/storage\/[^/]+\/content/.test(path)) return ok(DEMO_ISOS);

    // VM/CT corrente (stato in tempo reale)
    if (/^\/api\/clusters\/\d+\/vms\/[^/]+\/[^/]+\/\d+$/.test(path)) {
      const parts = path.split('/');
      const vmid = parts[parts.length - 1];
      return ok(buildVmDetail(vmid));
    }

    // RRD VM (grafici storici)
    if (/^\/api\/clusters\/\d+\/vms\/[^/]+\/[^/]+\/\d+\/rrd/.test(path)) return ok([]);

    // Snapshot
    if (/^\/api\/clusters\/\d+\/snapshots\//.test(path)) return ok(DEMO_SNAPSHOTS);

    // Backup list
    if (/^\/api\/clusters\/\d+\/backups\//.test(path)) return ok(DEMO_BACKUPS);

    // Task list (pannello tasks in basso a destra)
    if (path === '/api/tasks' || path === '/api/tasks?active=true') return ok(DEMO_TASKS);

    // Utenti
    if (path === '/api/users') return ok(DEMO_USERS);

    // Tieni passare tutto il resto (es. /api/auth/me per la sessione corrente)
    return null;
  };

  function ok(data) {
    return Promise.resolve(data);
  }


})();