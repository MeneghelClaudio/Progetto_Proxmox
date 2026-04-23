// Thin fetch wrapper + bearer token persistence
const TOKEN_KEY  = 'pmx_token';
const USER_KEY   = 'pmx_user';
const ROLE_KEY   = 'pmx_role';
const ADMIN_KEY  = 'pmx_admin';

export function saveToken(token, username, role = 'junior', isAdmin = false) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY,  username);
  localStorage.setItem(ROLE_KEY, role);
  localStorage.setItem(ADMIN_KEY, isAdmin ? '1' : '0');
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(ROLE_KEY);
  localStorage.removeItem(ADMIN_KEY);
}
export const getToken    = () => localStorage.getItem(TOKEN_KEY);
export const getUsername = () => localStorage.getItem(USER_KEY);
export const getRole     = () => localStorage.getItem(ROLE_KEY) || 'junior';
export const isAdmin     = () => localStorage.getItem(ADMIN_KEY) === '1';

export async function api(path, { method = 'GET', body = null, headers = {} } = {}) {
  const token = getToken();
  const opts = { method, headers: { ...headers } };
  if (token) opts.headers['Authorization'] = `Bearer ${token}`;
  if (body && !(body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    opts.body = body;
  }
  const r = await fetch(path, opts);
  if (r.status === 401) {
    clearToken();
    location.href = '/login.html';
    throw new Error('Unauthorized');
  }
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  if (r.status === 204) return null;
  const ct = r.headers.get('content-type') || '';
  return ct.includes('application/json') ? r.json() : r.text();
}
