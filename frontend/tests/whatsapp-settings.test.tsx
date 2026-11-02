import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { WhatsAppSettings } from '@/components/whatsapp-settings';

const state = vi.hoisted(() => ({ admin: true }));
vi.mock('@/components/providers', () => ({ useUser: () => ({ capabilities: { global_scope: state.admin } }) }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const config = { mode: 'mock', live_sends_enabled: false, bulk_sends_enabled: false, storage_ready: true,
  graph_version: 'v25.0', webhook_path: '/api/v1/whatsapp/webhook/', webhook_url: '', webhook_verified_at: null,
  access_token_configured: false, app_secret_configured: false, verify_token_configured: false };
function wrap() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><WhatsAppSettings /></QueryClientProvider>); }
beforeEach(() => {
  state.admin = true;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async path => path === '/whatsapp/settings/' ? config : { count: 1, next: null, previous: null, results: [{ id: 'account', name: 'LearnMore', branch_name: 'Central', is_active: true }] });
});

describe('WhatsApp connection setup', () => {
  it('saves write-only credentials, clears secret inputs and does not enable sends', async () => {
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === '/whatsapp/settings/') return options?.method ? { ...config, access_token_configured: true } : config;
      return { count: 0, results: [] };
    });
    wrap(); const user = userEvent.setup();
    const access = await screen.findByLabelText('Access token');
    expect(access).toHaveAttribute('type', 'password');
    await user.type(access, 'test-private-token');
    await user.type(screen.getByLabelText('Meta app secret'), 'test-private-secret');
    await user.click(screen.getByRole('button', { name: 'Save connection settings' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/whatsapp/settings/', { method: 'PATCH', body: { graph_version: 'v25.0', webhook_url: '', access_token: 'test-private-token', app_secret: 'test-private-secret' } }));
    expect(await screen.findByRole('status')).toHaveTextContent('Live messaging has not been enabled');
    expect(access).toHaveValue('');
    expect(screen.getByLabelText('Meta app secret')).toHaveValue('');
  });

  it('checks only saved account details without queuing a message', async () => {
    vi.mocked(api).mockImplementation(async path => {
      if (path === '/whatsapp/settings/') return { ...config, access_token_configured: true };
      if (path === '/whatsapp/settings/check/') return { connected: true, code: 'account_access_verified', detail: 'Meta confirms access.', display_phone_number: '+919876543210', verified_name: 'LearnMore' };
      return { count: 1, results: [{ id: 'account', name: 'LearnMore', branch_name: 'Central', is_active: true }] };
    });
    wrap(); const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText('Account to check'), 'account');
    await user.click(screen.getByRole('button', { name: 'Check Meta connection' }));
    expect(await screen.findByText('Account access verified')).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith('/whatsapp/settings/check/', { method: 'POST', body: { channel: 'account' } });
    expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('/messages/'))).toBe(false);
  });

  it('keeps credentials and check controls unavailable to non-administrators', async () => {
    state.admin = false; wrap();
    expect(await screen.findByText(/Ask your organization administrator/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Access token')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save connection settings' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check Meta connection' })).not.toBeInTheDocument();
  });

  it('generates and copies a verification token without saving it automatically', async () => {
    wrap(); const user = userEvent.setup();
    const clipboard = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    await user.click(await screen.findByRole('button', { name: 'Generate verification token' }));
    const field = screen.getByLabelText('Webhook verification token') as HTMLInputElement;
    expect(field.value).toMatch(/^[a-f0-9]{48}$/);
    await user.click(screen.getByRole('button', { name: 'Copy verification token' }));
    expect(clipboard).toHaveBeenCalledWith(field.value);
    expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false);
  });

  it('shows storage and connection failures clearly', async () => {
    vi.mocked(api).mockImplementation(async path => path === '/whatsapp/settings/' ? { ...config, storage_ready: false } : { count: 0, results: [] });
    wrap();
    expect(await screen.findByRole('button', { name: 'Save connection settings' })).toBeDisabled();
    expect(screen.getByText(/Secure credential storage needs/)).toBeInTheDocument();
  });
});
