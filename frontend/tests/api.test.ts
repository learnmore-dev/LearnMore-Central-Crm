import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, queryPath } from '@/lib/api';
const response = (data: unknown, status = 200) => new Response(data === null ? null : JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => vi.unstubAllGlobals());
describe('Django API client', () => {
  it('sends a fresh CSRF token, cookies and JSON for writes', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response({ csrfToken: 'rotated-token' })).mockResolvedValueOnce(response({ id: 'saved' }));
    vi.stubGlobal('fetch', fetcher);
    await expect(api('/branches/', { method: 'POST', body: { name: 'New' } })).resolves.toEqual({ id: 'saved' });
    expect(fetcher).toHaveBeenNthCalledWith(1, '/api/v1/auth/csrf/', expect.objectContaining({ credentials: 'include', cache: 'no-store' }));
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/v1/branches/', expect.objectContaining({ method: 'POST', credentials: 'include', headers: expect.objectContaining({ 'X-CSRFToken': 'rotated-token' }), body: '{"name":"New"}' }));
  });
  it('preserves duplicate-review payloads and readable field errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ full_name: ['This field is required.'] }, 400)));
    await expect(api('/contacts/')).rejects.toThrow('full_name: This field is required.');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ id: 'review-id', status: 'pending' }, 409)));
    try { await api('/contacts/'); } catch (error) { expect(error).toBeInstanceOf(ApiError); expect((error as ApiError).data).toMatchObject({ id: 'review-id' }); }
  });
  it('does not expire a session on a normal permission denial', async () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'You do not have permission to perform this action.' }, 403)));
    await expect(api('/branches/')).rejects.toBeInstanceOf(ApiError);
    expect(dispatch).not.toHaveBeenCalled();
  });
  it('signals an expired session and handles network failures', async () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'Authentication credentials were not provided.' }, 403)));
    await expect(api('/leads/')).rejects.toThrow();
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: 'crm-session-expired' }));
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')));
    await expect(api('/leads/')).rejects.toThrow('Cannot reach LearnMore Connect');
  });
  it('handles empty successful responses and rejects off-origin paths', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(null, 204)));
    await expect(api('/example/')).resolves.toBeNull();
    await expect(api('https://other.example/')).rejects.toThrow('Invalid CRM API path');
    await expect(api('//other.example/')).rejects.toThrow('Invalid CRM API path');
    expect(queryPath('/contacts/', { search: 'A & B', page: 2, branch: '' })).toBe('/contacts/?search=A+%26+B&page=2');
  });
});
