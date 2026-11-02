import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import InboxPage from '@/app/inbox/page';

vi.mock('@/components/providers', () => ({ useUser: () => ({ role: 'support', capabilities: { global_scope: false } }) }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const conversation = { id: 'c', channel: 'channel', channel_name: 'Central inbox', branch_name: 'Central', wa_id: '919876543210',
  contact: null, contact_name: null, consent: 'unknown', last_inbound_at: null, service_window_open: true, mode: 'mock', live_sends_enabled: false };
const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });
function wrap() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><InboxPage /></QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); });
function respond(row = conversation) {
  vi.mocked(api).mockImplementation(async path => {
    if (path.startsWith('/whatsapp/conversations/?')) return page([row]);
    if (path === '/whatsapp/conversations/c/') return row;
    return page([]);
  });
}
async function open() {
  await userEvent.setup().click(await screen.findByRole('button', { name: /\+919876543210/ }));
  return screen.findByRole('button', { name: 'Queue mock message' });
}

describe('shared WhatsApp inbox', () => {
  it('inserts a canned reply without sending it automatically', async () => {
    respond(); const reads = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, options) => path.startsWith('/whatsapp/canned-messages/') ? page([{ id: 'saved', title: 'Welcome', body: 'How can we help?' }]) : reads(path, options));
    wrap(); await open();
    await userEvent.setup().selectOptions(screen.getByLabelText('Insert canned reply'), 'saved');
    expect(screen.getByLabelText('Reply')).toHaveValue('How can we help?');
    expect(vi.mocked(api).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
  });
  it('blocks free-form replies outside the service window', async () => {
    respond({ ...conversation, service_window_open: false }); wrap();
    expect(await open()).toBeDisabled();
    expect(screen.getByLabelText('Reply')).toBeDisabled();
    expect(screen.getByText(/24-hour service window is closed/)).toBeInTheDocument();
    expect(screen.getByText(/No WhatsApp message will be sent/)).toBeInTheDocument();
  });
  it('retains a draft and idempotency key when queue submission fails', async () => {
    respond();
    const reads = vi.mocked(api).getMockImplementation()!;
    let attempts = 0;
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (options?.method === 'POST') {
        if (++attempts === 1) throw new Error('Queue temporarily unavailable');
        return { id: 'queued' };
      }
      return reads(path, options);
    });
    wrap(); const submit = await open(); const user = userEvent.setup();
    await user.type(screen.getByLabelText('Reply'), 'Hello from the team');
    await user.click(submit);
    expect(await screen.findByRole('alert')).toHaveTextContent('Queue temporarily unavailable');
    expect(screen.getByLabelText('Reply')).toHaveValue('Hello from the team');
    await user.click(submit);
    expect(await screen.findByRole('status')).toHaveTextContent('Message queued');
    const posts = vi.mocked(api).mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(2);
    expect(posts[0][1]?.body).toEqual(posts[1][1]?.body);
    expect(posts[1][1]?.body).toMatchObject({ conversation: 'c', text: 'Hello from the team' });
  });
});
