// Main view tabs: physical servers, cluster status, backup storage.
import { api } from './api.js';

let currentCredId = null;
let lastTree = null;

export function bindOverview(getCredId) {
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.addEventListener('click', () => switchTab(b.dataset.tab)));
  document.addEventListener('pmx:tree-loaded', (e) => {
    currentCredId = getCredId();
    lastTree = e.detail;
    renderAll();
  });
}

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    const active = b.dataset.tab === tab;
    b.classList.toggle('border-sky-500', active);
    b.classList.toggle('text-sky-300',   active);
    b.classList.toggle('border-transparent', !active);
    b.classList.toggle('text-slate-400',     !active);
  });
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
  document.getElementById('tab-' + tab).classList.remove('hidden');
}

function renderAll() {
  renderPhys();
  renderCluster();
  renderBackup();
}

function renderPhys() {
  const host = document.getElementById('tab-phys');
  if (!lastTree) { host.innerHTML = '<p class="text-slate-500 text-sm">Nessun dato</p>'; return; }
  host.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      ${lastTree.nodes.map(n => nodeCard(n)).join('')}
    </div>`;
}

function nodeCard(n) {
  const cpuPct = ((n.cpu||0)*100).toFixed(1);
  const memPct = n.maxmem ? ((n.mem/n.maxmem)*100).toFixed(1) : 0;
  const vms = n.vms?.length||0, cts = n.cts?.length||0;
  return `
  <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
    <div class="flex items-center justify-between">
      <div class="font-semibold flex items-center gap-2">🖥️ ${n.node}</div>
      <span class="text-xs px-2 rounded ${n.status==='online'?'bg-emerald-700':'bg-rose-800'}">${n.status}</span>
    </div>
    <div class="text-xs text-slate-400 mt-1">${n.ip || ''} · ${vms} VM · ${cts} CT</div>
    <div class="mt-2 text-xs">CPU ${cpuPct}%</div>
    <div class="progress"><span style="width:${cpuPct}%"></span></div>
    <div class="mt-2 text-xs">RAM ${memPct}%</div>
    <div class="progress"><span style="width:${memPct}%"></span></div>
  </div>`;
}

function renderCluster() {
  const host = document.getElementById('tab-cluster');
  const c = lastTree?.cluster;
  host.innerHTML = c ? `
    <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-4 max-w-lg">
      <h3 class="font-semibold text-lg flex items-center gap-2">🧩 ${c.name}</h3>
      <dl class="mt-2 text-sm grid grid-cols-2 gap-1">
        <dt class="text-slate-400">Nodes</dt><dd>${c.nodes||'?'}</dd>
        <dt class="text-slate-400">Quorate</dt>
        <dd>${c.quorate ? '<span class="text-emerald-400">sì</span>' : '<span class="text-rose-400">no</span>'}</dd>
        <dt class="text-slate-400">Version</dt><dd>${c.version||'-'}</dd>
      </dl>
    </div>` : '<p class="text-slate-500 text-sm">Modalità single-node</p>';
}

function renderBackup() {
  const host = document.getElementById('tab-backup');
  const targets = lastTree?.backup_targets || [];
  if (!targets.length) { host.innerHTML = '<p class="text-slate-500 text-sm">Nessuno storage di backup rilevato.</p>'; return; }
  host.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      ${targets.map(t => {
        const pct = t.total ? ((t.used/t.total)*100).toFixed(1) : 0;
        return `
        <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
          <div class="flex items-center justify-between">
            <div class="font-semibold flex items-center gap-2">💾 ${t.storage}</div>
            <div class="text-xs text-slate-400">${t.node}${t.shared?' · shared':''}</div>
          </div>
          <div class="text-xs mt-2">${fmtBytes(t.used)} / ${fmtBytes(t.total)} (${pct}%)</div>
          <div class="progress"><span style="width:${pct}%"></span></div>
        </div>`;
      }).join('')}
    </div>`;
}

function fmtBytes(n) {
  if (!n) return '0';
  const u = ['B','KB','MB','GB','TB']; let i=0;
  while (n >= 1024 && i < u.length-1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${u[i]}`;
}
