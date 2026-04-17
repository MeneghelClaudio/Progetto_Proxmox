// Bottom task bar: polls /api/tasks for active migrations and renders progress.

import { api } from './api.js';

let timer = null;

export function startTaskBar() {
  stopTaskBar();
  tick();
  timer = setInterval(tick, 3000);
}
export function stopTaskBar() { if (timer) { clearInterval(timer); timer = null; } }

async function tick() {
  let list = [];
  try { list = await api('/api/tasks?active=true'); }
  catch { list = []; }

  const host = document.getElementById('taskbarItems');
  const idle = document.getElementById('taskbarIdle');

  if (!list.length) {
    host.innerHTML = '';
    idle.classList.remove('hidden');
    return;
  }
  idle.classList.add('hidden');
  host.innerHTML = list.map(t => `
    <div class="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded px-2 py-1 min-w-[220px]">
      <span class="text-slate-400">${t.kind === 'qemu' ? '🧊' : '📦'} ${t.vmid}</span>
      <span>${t.source_node} → ${t.target_node}</span>
      <div class="progress flex-1"><span style="width:${t.progress}%"></span></div>
      <span class="text-slate-400 w-8 text-right">${t.progress}%</span>
    </div>`).join('');
}

// Kick a migration (called by the drag-drop handler)
export async function triggerMigration(credId, src, targetNode) {
  if (!confirm(`Migrare ${src.type} ${src.vmid} da ${src.node} a ${targetNode}?`)) return;
  try {
    await api(`/api/clusters/${credId}/vms/${src.type}/${src.node}/${src.vmid}/migrate`, {
      method: 'POST',
      body: { target_node: targetNode, online: src.status === 'running', with_local_disks: true },
    });
    tick();
  } catch (e) { alert(e.message); }
}
