// Right-panel "console" for the selected resource.
// VMware-Workstation-style: live charts + actions + snapshot history.

import { api } from './api.js';
import { mountCharts, subscribe, unsubscribe } from './charts.js';
import { confirmByName } from './modal.js';

let current = null;        // {type, node, vmid, ...}
let credId  = null;

export function bindDetail(getCredId) {
  credId = getCredId;
  document.addEventListener('pmx:select', (e) => show(e.detail));
}

export function refreshCredId(cid) { credId = () => cid; }

function show(obj) {
  current = obj;
  const host = document.getElementById('detail');
  unsubscribe();

  if (!obj) { host.innerHTML = '<p class="p-4 text-slate-500 text-sm">Seleziona…</p>'; return; }

  const cid = credId();
  if (obj.type === 'node') renderNode(host, cid, obj);
  else if (obj.type === 'qemu' || obj.type === 'lxc') renderGuest(host, cid, obj);
  else if (obj.type === 'storage') renderStorage(host, cid, obj);
  else host.innerHTML = `<pre class="p-3 text-xs">${JSON.stringify(obj, null, 2)}</pre>`;
}

// ---------- Node panel ----------

function renderNode(host, cid, n) {
  host.innerHTML = `
    <div class="p-4 space-y-3">
      <h2 class="font-semibold text-lg flex items-center gap-2">🖥️ ${n.node}</h2>
      <div class="grid grid-cols-2 gap-2 text-xs text-slate-400">
        <div>CPU: ${(n.cpu*100||0).toFixed(1)}% / ${n.maxcpu||'?'} core</div>
        <div>RAM: ${fmtBytes(n.mem)} / ${fmtBytes(n.maxmem)}</div>
        <div>Uptime: ${fmtUptime(n.uptime)}</div>
        <div>PVE: ${n.pve_version||'?'}</div>
      </div>
      <div class="chart-box"><div class="text-xs text-slate-400 mb-1">CPU (30m)</div>
        <div class="h-32"><canvas id="cpuChart"></canvas></div></div>
      <div class="chart-box"><div class="text-xs text-slate-400 mb-1">Memoria (30m)</div>
        <div class="h-32"><canvas id="memChart"></canvas></div></div>
    </div>`;
  mountCharts(host.querySelector('#cpuChart'), host.querySelector('#memChart'));
  subscribe(cid, `node/${n.node}`);
}

// ---------- Guest (VM / CT) panel ----------

function renderGuest(host, cid, v) {
  const kindLabel = v.type === 'qemu' ? 'VM' : 'Container';
  host.innerHTML = `
    <div class="p-4 space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold text-lg flex items-center gap-2">
          ${v.type === 'qemu' ? '🧊' : '📦'} ${v.vmid} · ${v.name}
        </h2>
        <span class="text-xs px-2 py-0.5 rounded ${v.status==='running'?'bg-emerald-700':'bg-slate-700'}">
          ${v.status}
        </span>
      </div>
      <div class="text-xs text-slate-400">Nodo: ${v.node} · ${kindLabel}</div>

      <div class="flex flex-wrap gap-2">
        <button data-a="start"    class="act bg-emerald-700 hover:bg-emerald-600 px-2 py-1 rounded text-xs">▶ Start</button>
        <button data-a="shutdown" class="act bg-amber-700  hover:bg-amber-600  px-2 py-1 rounded text-xs">⏻ Shutdown</button>
        <button data-a="stop"     class="act bg-red-700    hover:bg-red-600    px-2 py-1 rounded text-xs">■ Stop</button>
        <button data-a="reboot"   class="act bg-sky-700    hover:bg-sky-600    px-2 py-1 rounded text-xs">↻ Reboot</button>
        <button data-a="clone"    class="act bg-slate-700  hover:bg-slate-600  px-2 py-1 rounded text-xs">⎘ Clone</button>
        <button data-a="delete"   class="act bg-rose-800   hover:bg-rose-700   px-2 py-1 rounded text-xs">🗑 Delete</button>
      </div>

      <div class="chart-box"><div class="text-xs text-slate-400 mb-1">CPU (30m)</div>
        <div class="h-32"><canvas id="cpuChart"></canvas></div></div>
      <div class="chart-box"><div class="text-xs text-slate-400 mb-1">Memoria (30m)</div>
        <div class="h-32"><canvas id="memChart"></canvas></div></div>

      <div>
        <div class="flex items-center justify-between mt-3">
          <h3 class="text-sm font-semibold">Snapshot / History</h3>
          <button id="snapAdd" class="text-xs bg-sky-700 hover:bg-sky-600 px-2 py-1 rounded">+ Snapshot</button>
        </div>
        <table class="w-full text-xs mt-2">
          <thead class="text-slate-500 border-b border-slate-800">
            <tr><th class="text-left py-1">Nome</th><th class="text-left">Quando</th><th class="text-left">Descrizione</th><th></th></tr>
          </thead>
          <tbody id="snapBody"><tr><td colspan="4" class="text-slate-500 py-2">Caricamento…</td></tr></tbody>
        </table>
      </div>
    </div>`;

  mountCharts(host.querySelector('#cpuChart'), host.querySelector('#memChart'));
  subscribe(cid, `${v.type}/${v.node}/${v.vmid}`);

  host.querySelectorAll('.act').forEach(b => b.addEventListener('click', () => guestAction(cid, v, b.dataset.a)));
  host.querySelector('#snapAdd').addEventListener('click', () => createSnapshot(cid, v));
  loadSnapshots(cid, v);
}

async function guestAction(cid, v, action) {
  const base = `/api/clusters/${cid}/vms/${v.type}/${v.node}/${v.vmid}`;
  try {
    if (action === 'delete') {
      const ok = await confirmByName({
        title: `Elimina ${v.type === 'qemu' ? 'VM' : 'CT'} ${v.vmid}`,
        body:  `Digita il nome esatto per confermare: <b>${v.name}</b>. L'operazione è irreversibile.`,
        expected: v.name,
      });
      if (!ok) return;
      await api(base + '/delete', { method: 'POST', body: { confirm_name: v.name }});
    } else if (action === 'clone') {
      const newid = parseInt(prompt('Nuovo VMID:'), 10);
      if (!newid) return;
      const target = prompt(`Nodo destinazione (vuoto = stesso di ${v.node}):`) || null;
      const name   = prompt('Nome del clone (opzionale):') || null;
      const ok = await confirmByName({
        title: `Clone ${v.vmid} → ${newid}`,
        body:  `Verrà creata una nuova ${v.type==='qemu'?'VM':'CT'} ${newid}${target?' sul nodo '+target:''}. Digita il nome della sorgente per confermare: <b>${v.name}</b>.`,
        expected: v.name,
      });
      if (!ok) return;
      await api(base + '/clone', { method: 'POST',
        body: { newid, target_node: target, name, full: true }});
    } else {
      await api(base + '/' + action, { method: 'POST' });
    }
    flashOk(`Azione '${action}' inviata`);
  } catch (e) { flashErr(e.message); }
}

async function loadSnapshots(cid, v) {
  const body = document.getElementById('snapBody');
  try {
    const list = await api(`/api/clusters/${cid}/snapshots/${v.type}/${v.node}/${v.vmid}`);
    body.innerHTML = list.length === 0
      ? '<tr><td colspan="4" class="text-slate-500 py-2">Nessuno snapshot</td></tr>'
      : list.map(s => `
        <tr class="border-b border-slate-800/60">
          <td class="py-1 font-mono">${s.name}</td>
          <td>${s.snaptime ? new Date(s.snaptime*1000).toLocaleString() : ''}</td>
          <td class="text-slate-400">${escapeHtml(s.description || '')}</td>
          <td class="text-right">
            ${s.name !== 'current' ? `
              <button data-n="${s.name}" class="rb text-xs bg-slate-700 hover:bg-slate-600 px-1.5 rounded">rollback</button>
              <button data-n="${s.name}" class="rm text-xs bg-rose-800  hover:bg-rose-700 px-1.5 rounded">×</button>` : ''}
          </td></tr>`).join('');
    body.querySelectorAll('.rb').forEach(b => b.addEventListener('click', async () => {
      if (!confirm(`Rollback a '${b.dataset.n}'?`)) return;
      await api(`/api/clusters/${cid}/snapshots/${v.type}/${v.node}/${v.vmid}/${b.dataset.n}/rollback`,
                { method: 'POST' }); flashOk('Rollback inviato');
    }));
    body.querySelectorAll('.rm').forEach(b => b.addEventListener('click', async () => {
      if (!confirm(`Eliminare snapshot '${b.dataset.n}'?`)) return;
      await api(`/api/clusters/${cid}/snapshots/${v.type}/${v.node}/${v.vmid}/${b.dataset.n}`,
                { method: 'DELETE' }); flashOk('Snapshot eliminato'); loadSnapshots(cid, v);
    }));
  } catch (e) { body.innerHTML = `<tr><td colspan="4" class="text-red-400 py-2">${e.message}</td></tr>`; }
}

async function createSnapshot(cid, v) {
  const snapname = prompt('Nome dello snapshot (no spazi, max 40 char):');
  if (!snapname) return;
  const description = prompt('Descrizione (opzionale):') || '';
  try {
    await api(`/api/clusters/${cid}/snapshots/${v.type}/${v.node}/${v.vmid}`,
      { method: 'POST', body: { snapname, description, vmstate: false }});
    flashOk('Snapshot richiesto'); loadSnapshots(cid, v);
  } catch (e) { flashErr(e.message); }
}

function renderStorage(host, cid, s) {
  const pct = s.total ? (s.used / s.total * 100).toFixed(1) : 0;
  host.innerHTML = `
    <div class="p-4 space-y-3">
      <h2 class="font-semibold text-lg flex items-center gap-2">💽 ${s.storage}</h2>
      <div class="text-xs text-slate-400">Nodo: ${s.node}${s.shared ? ' · condiviso' : ''}</div>
      <div class="text-xs">Uso: ${fmtBytes(s.used)} / ${fmtBytes(s.total)} (${pct}%)</div>
      <div class="progress"><span style="width:${pct}%"></span></div>
      <div class="text-xs text-slate-500">Contenuti: ${s.content || '-'}</div>
    </div>`;
}

// ---------- helpers ----------
function fmtBytes(n) {
  if (!n) return '0';
  const u = ['B','KB','MB','GB','TB']; let i=0;
  while (n >= 1024 && i < u.length-1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${u[i]}`;
}
function fmtUptime(s) {
  if (!s) return '-';
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600), m = Math.floor((s%3600)/60);
  return `${d}g ${h}h ${m}m`;
}
function escapeHtml(x) { return String(x).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function toast(msg, cls) {
  const t = document.createElement('div');
  t.className = `fixed bottom-14 right-4 px-3 py-2 rounded shadow text-sm ${cls} z-50`;
  t.textContent = msg; document.body.append(t);
  setTimeout(() => t.remove(), 3500);
}
const flashOk  = (m) => toast(m, 'bg-emerald-600');
const flashErr = (m) => toast(m, 'bg-rose-700');
