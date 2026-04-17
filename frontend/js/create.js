// Dynamic VM/CT creation forms.
// openCreateVM(credId, nodeName) and openCreateCT(credId, nodeName) load the
// node's actual storages/networks/ISOs/templates and build a form accordingly.

import { api } from './api.js';
import { openModal } from './modal.js';

const fmtBytes = (n) => {
  if (!n) return '?'; const u=['B','KB','MB','GB','TB']; let i=0;
  while (n>=1024 && i<u.length-1) { n/=1024; i++; }
  return `${n.toFixed(1)} ${u[i]}`;
};

async function loadResources(credId, node) {
  return await api(`/api/clusters/${credId}/nodes/${node}/resources`);
}

function err(msg) { alert('Errore: ' + msg); }
function ok(msg)  {
  const t = document.createElement('div');
  t.className = 'fixed bottom-14 right-4 px-3 py-2 rounded shadow text-sm bg-emerald-600 z-50';
  t.textContent = msg; document.body.append(t);
  setTimeout(() => t.remove(), 3500);
}

// ========== VM (qemu) ==========

export async function openCreateVM(credId, node) {
  let res;
  try { res = await loadResources(credId, node); }
  catch (e) { return err(e.message); }

  const storageOpts = res.storages.vm_images.length
    ? res.storages.vm_images.map(s =>
        `<option value="${s.storage}">${s.storage} · ${s.type} · libero ${fmtBytes(s.avail)}</option>`).join('')
    : '<option value="" disabled>Nessuno storage "images" trovato</option>';

  const isoOpts = '<option value="">— nessuna (installa più tardi) —</option>' +
    res.iso_images.map(i => `<option value="${i.volid}">${i.volid} (${fmtBytes(i.size)})</option>`).join('');

  const bridgeOpts = res.networks.length
    ? res.networks.map(n => `<option value="${n.iface}">${n.iface}${n.comments ? ' · '+n.comments.trim() : ''}</option>`).join('')
    : '<option value="vmbr0">vmbr0</option>';

  const ostypeOpts = res.ostypes.map(o => `<option value="${o.value}">${o.label}</option>`).join('');
  const biosOpts   = res.bios_options.map(b => `<option value="${b.value}">${b.label}</option>`).join('');
  const netModels  = res.net_models.map(m => `<option value="${m}"${m==='virtio'?' selected':''}>${m}</option>`).join('');
  const fmtOpts    = res.disk_formats.map(f => `<option value="${f}"${f==='qcow2'?' selected':''}>${f}</option>`).join('');

  const m = openModal(`
    <h3 class="font-semibold flex items-center gap-2">🧊 Nuova VM su <span class="text-sky-300">${node}</span></h3>
    <form id="vmForm" class="space-y-2 text-sm max-h-[70vh] overflow-y-auto pr-1">

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Generale</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="col-span-1 text-xs text-slate-400">VMID
            <input name="vmid" type="number" min="100" value="${res.next_vmid}" required
                   class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="col-span-2 text-xs text-slate-400">Nome
            <input name="name" required placeholder="my-vm"
                   class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
        <label class="text-xs text-slate-400 block mt-1">OS type
          <select name="ostype" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${ostypeOpts}</select></label>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">CPU / Memoria</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-slate-400">Core
            <input name="cores" type="number" min="1" value="2" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="text-xs text-slate-400">Socket
            <input name="sockets" type="number" min="1" value="1" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="text-xs text-slate-400">RAM (MB)
            <input name="memory" type="number" min="16" value="2048" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Disco</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="col-span-2 text-xs text-slate-400">Storage
            <select name="disk_storage" required class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${storageOpts}</select></label>
          <label class="text-xs text-slate-400">Size (GB)
            <input name="disk_size" type="number" min="1" value="32" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
        <label class="text-xs text-slate-400 block mt-1">Formato
          <select name="disk_format" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${fmtOpts}</select></label>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Rete</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-slate-400">Bridge
            <select name="net_bridge" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${bridgeOpts}</select></label>
          <label class="text-xs text-slate-400">Modello
            <select name="net_model" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${netModels}</select></label>
          <label class="text-xs text-slate-400">VLAN (opz.)
            <input name="net_vlan" type="number" min="1" max="4094"
                   class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Boot / ISO</legend>
        <label class="text-xs text-slate-400 block">CD/DVD ISO
          <select name="iso_volid" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${isoOpts}</select></label>
        <div class="grid grid-cols-2 gap-2 mt-1">
          <label class="text-xs text-slate-400">BIOS
            <select name="bios" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${biosOpts}</select></label>
          <label class="text-xs text-slate-400 flex items-end gap-1">
            <input type="checkbox" name="machine_q35"> Machine q35
          </label>
        </div>
      </fieldset>

      <div class="flex items-center gap-4">
        <label class="text-xs flex items-center gap-1"><input type="checkbox" name="agent" checked> QEMU guest agent</label>
        <label class="text-xs flex items-center gap-1"><input type="checkbox" name="start"> Avvia dopo la creazione</label>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" id="cancel" class="text-sm px-3 py-1 rounded bg-slate-700">Annulla</button>
        <button type="submit" class="text-sm px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500">Crea VM</button>
      </div>
    </form>`);

  m.root.querySelector('#cancel').onclick = () => m.close();
  m.root.querySelector('#vmForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      vmid:     parseInt(fd.get('vmid'), 10),
      name:     fd.get('name').trim(),
      cores:    parseInt(fd.get('cores'), 10),
      sockets:  parseInt(fd.get('sockets'), 10),
      memory:   parseInt(fd.get('memory'), 10),
      ostype:   fd.get('ostype'),
      disk_storage: fd.get('disk_storage'),
      disk_size:    parseInt(fd.get('disk_size'), 10),
      disk_format:  fd.get('disk_format'),
      net_bridge:   fd.get('net_bridge'),
      net_model:    fd.get('net_model'),
      net_vlan:     fd.get('net_vlan') ? parseInt(fd.get('net_vlan'), 10) : null,
      iso_volid:    fd.get('iso_volid') || null,
      bios:         fd.get('bios'),
      machine:      fd.get('machine_q35') ? 'q35' : null,
      agent:        !!fd.get('agent'),
      start_after_create: !!fd.get('start'),
    };
    try {
      const r = await api(`/api/clusters/${credId}/nodes/${node}/qemu`,
        { method: 'POST', body });
      m.close();
      ok(`VM ${r.vmid} creata su ${node}`);
      document.dispatchEvent(new CustomEvent('pmx:tree-refresh'));
    } catch (ex) { err(ex.message); }
  });
}


// ========== Container (LXC) ==========

export async function openCreateCT(credId, node) {
  let res;
  try { res = await loadResources(credId, node); }
  catch (e) { return err(e.message); }

  if (!res.ct_templates.length) {
    return err(`Nessun template CT disponibile sul nodo "${node}". ` +
               `Scaricane uno da PVE: Datacenter > Storage > CT Templates.`);
  }

  const tmplOpts = res.ct_templates
    .map(t => `<option value="${t.volid}">${t.volid.replace(/^[^:]+:vztmpl\//,'')} (${fmtBytes(t.size)})</option>`).join('');
  const storageOpts = res.storages.ct_rootfs.length
    ? res.storages.ct_rootfs.map(s =>
        `<option value="${s.storage}">${s.storage} · ${s.type} · libero ${fmtBytes(s.avail)}</option>`).join('')
    : '<option value="" disabled>Nessuno storage "rootdir" trovato</option>';
  const bridgeOpts = res.networks.length
    ? res.networks.map(n => `<option value="${n.iface}">${n.iface}${n.comments ? ' · '+n.comments.trim() : ''}</option>`).join('')
    : '<option value="vmbr0">vmbr0</option>';

  const m = openModal(`
    <h3 class="font-semibold flex items-center gap-2">📦 Nuovo Container su <span class="text-sky-300">${node}</span></h3>
    <form id="ctForm" class="space-y-2 text-sm max-h-[70vh] overflow-y-auto pr-1">

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Generale</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-slate-400">CTID
            <input name="vmid" type="number" min="100" value="${res.next_vmid}" required
                   class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="col-span-2 text-xs text-slate-400">Hostname
            <input name="hostname" required placeholder="my-ct"
                   class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
        <label class="text-xs text-slate-400 block mt-1">Template
          <select name="ostemplate" required class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${tmplOpts}</select></label>
        <label class="text-xs flex items-center gap-1 mt-1"><input type="checkbox" name="unprivileged" checked> Unprivileged</label>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">CPU / Memoria</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-slate-400">Core
            <input name="cores" type="number" min="1" value="1" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="text-xs text-slate-400">RAM (MB)
            <input name="memory" type="number" min="16" value="512" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="text-xs text-slate-400">Swap (MB)
            <input name="swap" type="number" min="0" value="512" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Root disk</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="col-span-2 text-xs text-slate-400">Storage
            <select name="storage" required class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${storageOpts}</select></label>
          <label class="text-xs text-slate-400">Size (GB)
            <input name="disk_size" type="number" min="1" value="8" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Rete</legend>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-xs text-slate-400">Nome
            <input name="net_name" value="eth0" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
          <label class="text-xs text-slate-400">Bridge
            <select name="net_bridge" class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1">${bridgeOpts}</select></label>
          <label class="text-xs text-slate-400">IP
            <input name="net_ip" value="dhcp" placeholder="dhcp o 10.0.0.5/24"
                   class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        </div>
        <label class="text-xs text-slate-400 block mt-1">Gateway (solo IP statico)
          <input name="net_gw" placeholder="10.0.0.1"
                 class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
      </fieldset>

      <fieldset class="border border-slate-700 rounded p-2">
        <legend class="text-xs text-slate-400 px-1">Autenticazione (una delle due è obbligatoria)</legend>
        <label class="text-xs text-slate-400 block">Password root
          <input name="password" type="password" autocomplete="new-password"
                 class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1"></label>
        <label class="text-xs text-slate-400 block mt-1">SSH public keys
          <textarea name="ssh_public_keys" rows="2" placeholder="ssh-ed25519 AAAA..."
                    class="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 font-mono text-xs"></textarea></label>
      </fieldset>

      <div class="flex items-center gap-4">
        <label class="text-xs flex items-center gap-1"><input type="checkbox" name="onboot"> Avvio automatico al boot del nodo</label>
        <label class="text-xs flex items-center gap-1"><input type="checkbox" name="start"> Avvia dopo la creazione</label>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" id="cancel" class="text-sm px-3 py-1 rounded bg-slate-700">Annulla</button>
        <button type="submit" class="text-sm px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500">Crea CT</button>
      </div>
    </form>`);

  m.root.querySelector('#cancel').onclick = () => m.close();
  m.root.querySelector('#ctForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      vmid:       parseInt(fd.get('vmid'), 10),
      hostname:   fd.get('hostname').trim(),
      ostemplate: fd.get('ostemplate'),
      cores:      parseInt(fd.get('cores'), 10),
      memory:     parseInt(fd.get('memory'), 10),
      swap:       parseInt(fd.get('swap'), 10),
      storage:    fd.get('storage'),
      disk_size:  parseInt(fd.get('disk_size'), 10),
      unprivileged: !!fd.get('unprivileged'),
      net_name:   fd.get('net_name') || 'eth0',
      net_bridge: fd.get('net_bridge'),
      net_ip:     fd.get('net_ip') || 'dhcp',
      net_gw:     fd.get('net_gw') || null,
      password:   fd.get('password') || null,
      ssh_public_keys: fd.get('ssh_public_keys') || null,
      onboot:     !!fd.get('onboot'),
      start_after_create: !!fd.get('start'),
    };
    if (!body.password && !body.ssh_public_keys) return err('Inserisci password o chiave SSH');
    try {
      const r = await api(`/api/clusters/${credId}/nodes/${node}/lxc`,
        { method: 'POST', body });
      m.close();
      ok(`Container ${r.vmid} creato su ${node}`);
      document.dispatchEvent(new CustomEvent('pmx:tree-refresh'));
    } catch (ex) { err(ex.message); }
  });
}
