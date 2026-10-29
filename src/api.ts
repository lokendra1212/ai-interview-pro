// In local development use Vite's same-origin /api proxy to avoid browser CORS
// failures when the app is opened as localhost or 127.0.0.1.
const API = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || 'http://localhost:8000');
export function setToken(token: string | null) { if (token) sessionStorage.setItem('aip-token', token); else sessionStorage.removeItem('aip-token'); }
export function getToken() { return sessionStorage.getItem('aip-token'); }
async function fetchApi(path: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API}${path}`, options);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error('Cannot reach the API. Check VITE_API_URL and make sure the backend is running.');
    }
    throw error;
  }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const token = getToken(); if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetchApi(path, { ...options, headers });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed (${response.status})`); }
  return response.json();
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetchApi(path, { headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
