import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { WhatsAppNav } from '@/components/whatsapp-nav';
import { WhatsAppWorkspace } from '@/components/whatsapp-workspace';
import QRCode from 'qrcode';

const state = vi.hoisted(() => ({ user: { branch: 'branch', role: 'branch_manager', capabilities: { global_scope: true, manage_routing: true } } }));
vi.mock('@/components/providers', () => ({ useUser: () => state.user }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,AAA') } }));
const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });
function wrap(section: string) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><WhatsAppWorkspace section={section} /></QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); state.user.capabilities = { global_scope: true, manage_routing: true }; });

describe('WhatsApp workspace', () => {
  it('matches the complete expandable submenu and highlights the active page', async () => {
    render(<WhatsAppNav pathname="/whatsapp/templates" onNavigate={vi.fn()} />);
    expect(screen.getAllByRole('link')).toHaveLength(8);
    expect(screen.getByRole('link', { name: 'Templates' })).toHaveAttribute('aria-current', 'page');
    await userEvent.setup().click(screen.getByRole('button', { name: 'WhatsApp' }));
    expect(screen.queryByRole('link', { name: 'Campaigns' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'WhatsApp' })).toHaveAttribute('aria-expanded', 'false');
  });
  it('saves a reusable branch reply', async () => {
    vi.mocked(api).mockImplementation(async path => path.startsWith('/branches/') ? page([{ id: 'branch', name: 'Central' }]) : page([]));
    wrap('canned-messages'); const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Add saved reply' }));
    await user.type(screen.getByLabelText('Reply title'), 'Welcome');
    await user.type(screen.getByRole('textbox', { name: 'Saved reply' }), 'How can we help?');
    await user.click(screen.getByRole('button', { name: 'Save reply' }));
    expect(api).toHaveBeenCalledWith('/whatsapp/canned-messages/', { method: 'POST', body: { branch: 'branch', title: 'Welcome', body: 'How can we help?', is_active: true } });
  });
  it('hides manager reply controls from regular staff', async () => {
    state.user.capabilities = { global_scope: false, manage_routing: false };
    vi.mocked(api).mockResolvedValue(page([])); wrap('canned-messages');
    expect(await screen.findByText('No saved replies yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add saved reply' })).not.toBeInTheDocument();
  });
  it('generates QR links from the public business number rather than the Meta phone ID', async () => {
    vi.mocked(api).mockResolvedValue(page([{ id: 'channel', name: 'Central', business_phone: '+919876543210', phone_number_id: '12345', is_active: true }]));
    wrap('chat-widget'); const user = userEvent.setup();
    await screen.findByRole('option', { name: /Central/ });
    await user.selectOptions(await screen.findByLabelText('Business account'), 'channel');
    const chatLink = await screen.findByLabelText('Chat link') as HTMLInputElement;
    expect(chatLink.value).toContain('https://wa.me/919876543210?text=');
    expect(QRCode.toDataURL).toHaveBeenCalledWith(expect.stringContaining('https://wa.me/919876543210?text='), expect.any(Object));
    expect(await screen.findByRole('link', { name: 'Download QR PNG' })).toHaveAttribute('download', 'whatsapp-chat-qr.png');
  });
  it('shows mock campaign safeguards without claiming live functionality', async () => {
    vi.mocked(api).mockImplementation(async path => path === '/whatsapp/settings/' ? { mode: 'mock', live_sends_enabled: false } : page([]));
    wrap('campaigns');
    expect(await screen.findByText('No campaigns yet')).toBeInTheDocument();
    expect(screen.getByText(/Live bulk sends are disabled/)).toBeInTheDocument();
  });
});
