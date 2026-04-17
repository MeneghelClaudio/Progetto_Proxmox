// Sidebar tree rendering + selection events.
// Emits a CustomEvent('pmx:select', { detail: node }) on document.

import { api } from './api.js';

let state = { tree: null, selectedKey: null };
const ICON = {
  cluster: '🧩', node: '🖥️', qemu: '🧊', lxc: '📦',
  storage: '💽', backup: '💾',
};

export async function loadTree(credId) {
  if (!credId) { render(document.getElementById('tree'), null); return; }
  state.tree = await api(`/api/clusters/${credId}/tree`);
  render(document.getElementById('tree'), state.tree);
}

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k.startsWith('on'))  n.addEventListener(k.slice(2), v);
    else if (k === 'data')  Object.assign(n.dataset, v);
    else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(k));
  return n;
}

function nodeRow(obj, label, emoji, statusClass) {
  const key = `${obj.type}:${obj.node || ''}:${obj.vmid || obj.storage || obj.name || ''}`;
  const row = el('div', {
    class: 'tree-node' + (state.selectedKey === key ? ' selected' : ''),
    data: { key, type: obj.type, payload: JSON.stringify(obj) },
    draggable: obj.type === 'qemu' || obj.type === 'lxc',
    onclick: () => select(key, obj),
    ondragstart: (e) => {
      e.dataTransfer.setData('application/json', JSON.stringify(obj));
      e.dataTransfer.effectAllowed = 'move';
    },
  }, emoji, statusClass ? el('span', { class: 'dot ' + statusClass }) : null, label);

  if (obj.type === 'node') {
    // Allow dropping VMs/CTs onto a node → triggers migration
    row.addEventListener('dragover', (e) => { e.preventDefault(); row.classList.add('dragover'); });
    row.addEventListener('dragleave', () => row.classList.remove('dragover'));
    row.addEventListener('drop', (e) => {
      e.preventDefault(); row.classList.remove('dragover');
      try {
        const src = JSON.parse(e.dataTransfer.getData('application/json'));
        document.dispatchEvent(new CustomEvent('pmx:migrate-request',
          { detail: { src, targetNode: obj.node } }));
      } catch {}
    });
  }
  return row;
}

function render(host, data) {
  host.innerHTML = '';
  if (!data) { host.append(el('div', { class: 'text-slate-500 p-2' }, 'Nessun cluster')); return; }

  const clusterName = data.cluster?.name || 'Cluster';
  host.append(el('div', { class: 'tree-node font-semibold' },
    ICON.cluster, clusterName));

  const nodesGroup = el('div', { class: 'tree-children' });
  for (const n of data.nodes) {
    const nodeRowEl = nodeRow({ ...n, type: 'node' },
      n.node, ICON.node, n.status === 'online' ? 'running' : 'offline');
    nodesGroup.append(nodeRowEl);

    const childWrap = el('div', { class: 'tree-children' });
    if (n.vms?.length) {
      childWrap.append(el('div', { class: 'text-slate-500 text-xs px-1 mt-1' }, 'VM'));
      for (const v of n.vms) childWrap.append(nodeRow(v, `${v.vmid} · ${v.name}`,
        ICON.qemu, v.status === 'running' ? 'running' : 'stopped'));
    }
    if (n.cts?.length) {
      childWrap.append(el('div', { class: 'text-slate-500 text-xs px-1 mt-1' }, 'Container'));
      for (const c of n.cts) childWrap.append(nodeRow(c, `${c.vmid} · ${c.name}`,
        ICON.lxc, c.status === 'running' ? 'running' : 'stopped'));
    }
    if (n.storages?.length) {
      childWrap.append(el('div', { class: 'text-slate-500 text-xs px-1 mt-1' }, 'Storage'));
      for (const s of n.storages) childWrap.append(nodeRow({ ...s, type: 'storage' },
        s.storage, ICON.storage));
    }
    nodesGroup.append(childWrap);
  }
  host.append(nodesGroup);

  if (data.backup_targets?.length) {
    host.append(el('div', { class: 'tree-node font-semibold mt-2' }, ICON.backup, 'Backup Storage'));
    const bw = el('div', { class: 'tree-children' });
    for (const b of data.backup_targets)
      bw.append(nodeRow({ ...b, type: 'storage' }, `${b.storage} @ ${b.node}`, ICON.backup));
    host.append(bw);
  }
}

function select(key, obj) {
  state.selectedKey = key;
  document.querySelectorAll('.tree-node.selected').forEach(n => n.classList.remove('selected'));
  document.querySelectorAll(`.tree-node[data-key="${CSS.escape(key)}"]`)
    .forEach(n => n.classList.add('selected'));
  document.dispatchEvent(new CustomEvent('pmx:select', { detail: obj }));
}

export const getTree = () => state.tree;
