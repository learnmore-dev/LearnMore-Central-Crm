import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { GoogleContacts } from '@/components/google-contacts';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
const identity = { capabilities: { manage_users: true } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
const status = { configured: false, configuration_errors: ['GOOGLE_CONTACTS_CLIENT_ID'], state: 'disconnected', email: '', automatic: false, interval_minutes: 15, last_worker_at: null, worker_stale: true, last_success_at: null, last_error: '', callback_url: 'http://127.0.0.1:3100/api/v1/integrations/google-contacts/callback/', crm_origin: '' };
const job = { id: 'job', email: 'shared@example.com', status: 'preview', automatic: false, actor_name: 'admin', created_at: '2026-11-02T10:00:00+05:30', counts: { create: 1, update: 0 } };
const row = { id: 1, contact_name: 'Rahul', contact_label: 'LMT-C-000042', action: 'create', status: 'planned', reason: '', candidates: [], payload: { names: [{ givenName: 'Rahul · LMT-C-000042' }], phoneNumbers: [{ value: '+919876543210' }], biographies: [{ value: 'First enquiry: 02 Nov 2026\nLMT-KN-L-000099 | Python | Asha' }] } };
const page = (results: unknown[]) => ({ count: results.length, results, next: null, previous: null });
function wrap() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><GoogleContacts /></QueryClientProvider>); }
function mock(connected = false, withJob = false) {
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/integrations/google-contacts/') return connected ? { ...status, configured: true, configuration_errors: [], state: 'connected', email: 'shared@example.com' } : status;
    if (path === '/integrations/google-contacts/preview/' && options?.method) return job;
    if (path === '/integrations/google-contact-jobs/job/') return job;
    if (path.startsWith('/integrations/google-contact-jobs/?')) return page(withJob ? [job] : []);
    if (path.startsWith('/integrations/google-contact-items/?')) return page([row]);
    return {};
  });
}
beforeEach(() => { identity.capabilities.manage_users = true; vi.mocked(api).mockReset(); mock(); });

describe('shared Google Contacts integration', () => {
  it('restricts the integration to administrators', () => {
    identity.capabilities.manage_users = false; wrap();
    expect(screen.getByText('Administrator access required')).toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });
  it('explains missing configuration and disables Google connection', async () => {
    wrap();
    expect(await screen.findByText('Finish the server setup')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect Google account' })).toBeDisabled();
    expect(screen.getByText('GOOGLE_CONTACTS_CLIENT_ID')).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method)).toBe(false);
  });
  it('builds a preview without automatically starting Google writes', async () => {
    mock(true); wrap(); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Preview contact sync' }));
    expect(await screen.findByText('Rahul · LMT-C-000042')).toBeInTheDocument();
    expect(screen.getByText(/First enquiry: 02 Nov 2026/)).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.filter(([, options]) => options?.method).map(([path]) => path)).toEqual(['/integrations/google-contacts/preview/']);
  });
  it('requires an explicit destination confirmation before queueing sync', async () => {
    mock(true, true); wrap(); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Review & sync' }));
    expect(screen.getByText('Destination: shared@example.com')).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/start/'))).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Sync these contacts' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/integrations/google-contact-jobs/job/start/', { method: 'POST' }));
  });
  it('explains the queue worker and confirms disconnect without deleting contacts', async () => {
    mock(true); wrap(); const user = userEvent.setup();
    expect(await screen.findByText('Background worker has not checked in recently')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(screen.getByText(/Contacts already in Google are kept/)).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/disconnect/'))).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Disconnect CRM sync' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/integrations/google-contacts/disconnect/', { method: 'POST' }));
  });
});
