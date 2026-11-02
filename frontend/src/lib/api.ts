function describe(value: unknown, path = ''): string[] {
  if (typeof value === 'string') return [path ? `${path}: ${value}` : value];
  if (Array.isArray(value)) return value.flatMap(item => describe(item, path));
  if (value && typeof value === 'object') return Object.entries(value).flatMap(([key, item]) => describe(item, key === 'detail' || key === 'non_field_errors' ? path : [path, key].filter(Boolean).join('.')));
  return [];
}
export class ApiError extends Error {
  constructor(public status: number, public data: unknown) {
    super(describe(data).join(' ') || ([502, 503].includes(status) ? 'The CRM service is unavailable. Please try again.' : `The request failed (${status}).`));
    this.name = 'ApiError';
  }
}
export function isSessionExpired(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.status === 401 ||
    (error.status === 403 && error.message.includes('Authentication credentials were not provided')));
}
export async function api<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://') || path.includes('..')) throw new Error('Invalid CRM API path.');
  const method = options.method || 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = await api<{ csrfToken: string }>('/auth/csrf/', { signal: options.signal });
    headers['X-CSRFToken'] = csrf.csrfToken;
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch('/api/v1/' + path.slice(1), { method, credentials: 'include', cache: 'no-store', headers,
      signal: options.signal, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new Error('Cannot reach LearnMore Connect. Check your connection and try again.');
  }
  let data: unknown = null;
  if (response.status !== 204) {
    if (response.headers.get('content-type')?.includes('application/json')) data = await response.json();
    else if (response.ok) throw new Error('The CRM returned an unexpected response. Please try again.');
  }
  if (!response.ok) {
    const error = new ApiError(response.status, data);
    if (typeof window !== 'undefined' && !path.startsWith('/auth/login') && isSessionExpired(error)) window.dispatchEvent(new Event('crm-session-expired'));
    throw error;
  }
  return data as T;
}
export function queryPath(path: string, params: Record<string, string | number | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value));
  return path + (query.size ? `?${query}` : '');
}
