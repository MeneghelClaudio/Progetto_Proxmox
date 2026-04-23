// App entry point. Wires: auth guard, credential picker, tree, detail panel,
// overview tabs, task bar, drag & drop migration.

import { api, getToken, getUsername, getRole, clearToken } from './api.js';
import { loadTree } from './tree.js';
import { bindDetail, refreshCredId } from './detail.js';
import { bindOverview } from './overview.js';
import { startTaskBar, triggerMigration } from './tasks.js';
import { openModal } from './modal.js';

// --- Auth guard ---
if (!getToken()) location.href = '/login.html';

document.getElementById('userLabel').textContent = getUsername() || '';
const role = getRole();
document.getElementById('userLabel').textContent = `${getUsername() || ''} (${role})`;
document.getElementById('logoutBtn').addEventListener('click', () => {
  clearToken(); location.href = '/login.html';
});
if (role === 'admin') {
  const usersBtn = document.getElementById('usersBtn');
  usersBtn.classList.remove('hidden');
  usersBtn.addEventListener('click', () => { location.href = '/users.html'; });
}

// --- Credential picker ---
const credSelect = document.getElementById('credSelect');
let currentCredId = null;
const getCredId = () => currentCredId;

bindDetail(getCredId);
bindOverview(getCredId);
startTaskBar();

async function loadCredentials() {
  const list = await api('/api/credentials');
  credSelect.innerHTML =
    '<option value="">— seleziona cluster —</option>' +
    list.map(c => `<option value="${c.id}">${c.name} (${c.host})</option>`).join('');
  if (list.length) { credSelect.value = list[0].id; onCredChanged(); }
}

credSelect.addEventListener('change', onCredChanged);

async function onCredChanged() {
  currentCredId = credSelect.value ? parseInt(credSelect.value, 10) : null;
  refreshCredId(currentCredId);
  if (!currentCredId) return;
  try {
    await loadTree(currentCredId);
    // Re-fetch the tree payload so overview has fresh data
    const data = await api(`/api/clusters/${currentCredId}/tree`);
    document.dispatchEvent(new CustomEvent('pmx:tree-loaded', { detail: data }));
  } catch (e) { alert('Errore caricamento cluster: ' + e.message); }
}

// --- Drag & drop migration request routed through task bar ---
document.addEventListener('pmx:migrate-request', async (e) => {
  const { src, targetNode } = e.detail;
  if (!currentCredId) return;
  if (src.node === targetNode) return;
  await triggerMigration(currentCredId, src, targetNode);
});

// --- Refresh tree after a create / destructive action ---
document.addEventListener('pmx:tree-refresh', () => {
  if (currentCredId) onCredChanged();
});

// --- Add credential modal ---
document.getElementById('addCredBtn').addEventListener('click', () => {
  const m = openModal(`
    <h3 class="font-semibold">Nuovo cluster Proxmox</h3>
    <form id="credForm" class="space-y-2 text-sm">
      <input name="name" placeholder="Etichetta (es. homelab)" required
             class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1" />
      <div class="flex gap-2">
        <input name="host" placeholder="pve.example.com" required
               class="flex-1 bg-slate-950 border border-slate-700 rounded px-2 py-1" />
        <input name="port" type="number" value="8006"
               class="w-24 bg-slate-950 border border-slate-700 rounded px-2 py-1" />
      </div>
      <div class="flex gap-2">
        <input name="pve_username" placeholder="root" required value="root"
               class="flex-1 bg-slate-950 border border-slate-700 rounded px-2 py-1" />
        <select name="pve_realm"
               class="bg-slate-950 border border-slate-700 rounded px-2 py-1">
          <option>pam</option><option>pve</option>
        </select>
      </div>
      <input name="password" type="password" placeholder="Password Proxmox" required
             class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1" />
      <label class="text-xs text-slate-400 flex items-center gap-2">
        <input type="checkbox" name="verify_ssl" /> Verifica certificato SSL (OFF per self-signed)
      </label>
      <div class="flex justify-end gap-2 pt-2">
        <button type="button" id="credCancel" class="text-sm px-3 py-1 rounded bg-slate-700">Annulla</button>
        <button type="submit" class="text-sm px-3 py-1 rounded bg-sky-600">Salva</button>
      </div>
    </form>`);
  m.root.querySelector('#credCancel').onclick = () => m.close();
  m.root.querySelector('#credForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      name: fd.get('name'), host: fd.get('host'),
      port: parseInt(fd.get('port') || '8006', 10),
      pve_username: fd.get('pve_username'),
      pve_realm: fd.get('pve_realm'),
      password: fd.get('password'),
      verify_ssl: !!fd.get('verify_ssl'),
    };
    try {
      await api('/api/credentials', { method: 'POST', body });
      m.close();
      await loadCredentials();
    } catch (ex) { alert(ex.message); }
  });
});

loadCredentials().catch(e => alert(e.message));
