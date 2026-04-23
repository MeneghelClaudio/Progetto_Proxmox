import { api, getToken, getRole, clearToken } from './api.js';

if (!getToken()) location.href = '/login.html';
if (getRole() !== 'admin') location.href = '/index.html';

document.getElementById('backBtn').addEventListener('click', () => { location.href = '/index.html'; });
document.getElementById('logoutBtn').addEventListener('click', () => { clearToken(); location.href = '/login.html'; });

const usersList = document.getElementById('usersList');
const addWrap = document.getElementById('addWrap');
document.getElementById('addBtn').addEventListener('click', () => addWrap.classList.toggle('hidden'));
document.getElementById('cancelAdd').addEventListener('click', () => addWrap.classList.add('hidden'));

document.getElementById('addForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api('/api/auth/users', {
    method: 'POST',
    body: {
      username: fd.get('username'),
      password: fd.get('password'),
      role: fd.get('role'),
    },
  });
  e.target.reset();
  addWrap.classList.add('hidden');
  await loadUsers();
});

async function loadUsers() {
  const users = await api('/api/auth/users');
  usersList.innerHTML = users.map((u) => `
    <div class="card" style="margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div style="font-weight:700">${u.username}</div>
        <div class="text-muted">ruolo: ${u.role}</div>
      </div>
      <button class="btn btn-secondary btn-sm del-user" data-id="${u.id}" ${u.username === 'admin' ? 'disabled' : ''}>Elimina</button>
    </div>
  `).join('');

  usersList.querySelectorAll('.del-user').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = Number(btn.dataset.id);
      if (!id) return;
      await api(`/api/auth/users/${id}`, { method: 'DELETE' });
      await loadUsers();
    });
  });
}

loadUsers().catch((e) => {
  usersList.innerHTML = `<div class="text-muted">Errore caricamento utenti: ${e.message}</div>`;
});
