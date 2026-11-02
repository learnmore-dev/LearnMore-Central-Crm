import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { InboxIdentity, type IntakeConversation } from '@/components/inbox-identity';
import { ContactHistory } from '@/components/contact-history';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const identity = { role: 'branch_manager', capabilities: { global_scope: false } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
const conversation: IntakeConversation = { id: 'chat', contact: 'contact', contact_label: 'LM-C-00042', identity_status: 'matched', ownership: { lead: 'lead', lead_label: 'LM-L-00099', owner_name: 'Asha', course: 'Python', status: 'new' } };
function wrap(child: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{child}</QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); identity.role = 'branch_manager'; });

describe('WhatsApp identity and shared history', () => {
  it('shows stable IDs and responsible counsellor without starting any work', () => {
    wrap(<InboxIdentity conversation={conversation} />);
    expect(screen.getByText('LM-C-00042')).toBeInTheDocument();
    expect(screen.getByText('Asha')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /LM-L-00099/ })).toHaveAttribute('href', '/leads/lead');
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
  it('lets managers resolve a shared-phone review with an explicit reason', async () => {
    vi.mocked(api).mockResolvedValue({});
    wrap(<InboxIdentity conversation={{ id: 'chat', contact: null, identity_status: 'review', review_candidates: [{ id: 'candidate', contact_id: 'LM-C-00042', full_name: 'Student A' }] }} />);
    const user = userEvent.setup(); await user.click(screen.getByRole('button', { name: 'Review identity' }));
    await user.selectOptions(screen.getByLabelText('Existing contact'), 'candidate');
    await user.type(screen.getByLabelText('Verification reason'), 'Confirmed with student');
    await user.click(screen.getByRole('button', { name: 'Confirm identity' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/whatsapp/conversations/chat/resolve-identity/', { method: 'POST', body: { decision: 'linked', contact: 'candidate', reason: 'Confirmed with student' } }));
  });
  it('does not expose manager identity or enquiry controls to counsellors', () => {
    identity.role = 'counsellor';
    wrap(<InboxIdentity conversation={{ ...conversation, identity_status: 'review' }} />);
    expect(screen.queryByRole('button', { name: 'Review identity' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Choose / create enquiry' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Chats, calls & notes' })).toBeInTheDocument();
  });
  it('shows attributed calls and chat history with source filters', async () => {
    vi.mocked(api).mockResolvedValue({ count: 1, has_next: false, enquiries: [{ id: 'lead', lead_id: 'LM-L-00099', title: 'Python', status: 'new', branch: 'Central', owner: 'Asha' }], results: [{ id: 'call', source: 'call', title: 'Outgoing call · answered', body: 'Discussed weekend batch', actor: 'Asha', branch: 'Central', occurred_at: '2026-11-02T10:00:00+05:30', status: 'answered', mode: 'manual', target: '/calls?search=919876543210' }] });
    wrap(<ContactHistory contactId="contact" />);
    expect(await screen.findByText('Discussed weekend batch')).toBeInTheDocument();
    expect(screen.getByText('Asha · Central · manual')).toBeInTheDocument();
    await userEvent.setup().selectOptions(screen.getByLabelText('History source'), 'whatsapp');
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('/contacts/contact/history/?source=whatsapp'))).toBe(true));
  });
});
