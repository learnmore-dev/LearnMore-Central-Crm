import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Profile } from '@/lib/types';
import { api } from '@/lib/api';
import { LoginForm } from '@/components/login';
import BranchesPage from '@/app/branches/page';
import ContactsPage from '@/app/contacts/page';
import LeadsPage from '@/app/leads/page';
import CounsellorsPage from '@/app/counsellors/page';
import AssignmentsPage from '@/app/assignments/page';
import EnquiriesPage from '@/app/enquiries/page';
import CallsPage from '@/app/calls/page';

const state = vi.hoisted(() => ({ user: { id: 'u', role: 'support', capabilities: { sales_write: false, manage_branches: false, global_scope: false, manage_routing: false } } as Profile }));
vi.mock('@/components/providers', () => ({ useUser: () => state.user }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
function wrap(child: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{child}</QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); state.user.capabilities = { sales_write: false, manage_branches: false, global_scope: false, manage_routing: false }; });
describe('workspace states and permissions', () => {
  it('creates an enquiry from the call row action', async () => {
    state.user.capabilities.sales_write = true;
    vi.mocked(api).mockResolvedValue({ count: 1, next: null, previous: null, results: [
      { id: 'call', caller_phone: '+919876543210', contact: 'contact', contact_name: 'Student', status: 'answered', direction: 'incoming', started_at: '2026-10-25T09:00:00Z', duration_seconds: 90, forwarded_to: 'Manager 1', branch_name: 'Central', identity_status: 'linked', candidates: [], lead: null },
    ] });
    wrap(<CallsPage />); const user = userEvent.setup();
    expect(await screen.findByText('Student')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create enquiry' }));
    await user.clear(screen.getByLabelText('Enquiry title / course'));
    await user.type(screen.getByLabelText('Enquiry title / course'), 'Python enquiry');
    await user.click(screen.getAllByRole('button', { name: 'Create enquiry' }).at(-1)!);
    expect(api).toHaveBeenCalledWith('/call-logs/call/create-enquiry/', { method: 'POST', body: { title: 'Python enquiry' } });
  });
  it('shows the disconnected call state without write access for support', async () => {
    vi.mocked(api).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    wrap(<CallsPage />);
    expect(await screen.findByText('No call logs yet')).toBeInTheDocument();
    expect(screen.getByText('MyOperator API is not connected yet.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add call log' })).not.toBeInTheDocument();
  });
  it('shows website enquiry identity reviews without granting support resolution rights', async () => {
    vi.mocked(api).mockResolvedValue({ count: 1, next: null, previous: null, results: [
      { id: 'submission', website: 'learnmoretech.in', full_name: 'New Student', phone: '+919876543210', course: 'Python', branch_name: 'Central', status: 'review', created_at: '2026-10-25T09:00:00Z', candidates: [] },
    ] });
    wrap(<EnquiriesPage />);
    expect(await screen.findByText('New Student')).toBeInTheDocument();
    expect(screen.getByText('Identity review')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review identity' })).not.toBeInTheDocument();
  });
  it('allows managers to confirm identity and create an enquiry from a website submission', async () => {
    state.user.capabilities.manage_routing = true;
    vi.mocked(api).mockResolvedValue({ count: 1, next: null, previous: null, results: [
      { id: 'submission', website: 'learnmoretech.in', full_name: 'New Student', phone: '+919876543210', course: 'Python', branch_name: 'Central', status: 'review', created_at: '2026-10-25T09:00:00Z', candidates: [{ id: 'contact', full_name: 'Existing Student', contact_id: 'LM-C-001' }] },
    ] });
    wrap(<EnquiriesPage />); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Review identity' }));
    await user.selectOptions(screen.getByLabelText('Existing contact'), 'contact');
    await user.type(screen.getByLabelText('Review reason'), 'Confirmed same student');
    await user.click(screen.getByRole('button', { name: 'Confirm identity decision' }));
    expect(api).toHaveBeenCalledWith('/website-enquiries/submission/resolve/', { method: 'POST', body: { decision: 'linked', reason: 'Confirmed same student', contact: 'contact' } });
  });
  it('allows counsellors to manage their own availability only', async () => {
    vi.mocked(api).mockResolvedValue({ count: 2, next: null, previous: null, results: [
      { id: 1, user: 'u', user_name: 'Self', user_active: true, is_available: true, can_receive_leads: true, workload: 2, max_active_leads: 10 },
      { id: 2, user: 'other', user_name: 'Colleague', user_active: true, is_available: false, can_receive_leads: true, workload: 0, max_active_leads: 10 },
    ] });
    wrap(<CounsellorsPage />);
    expect(await screen.findByText('Self')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Manage' })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Enable counsellor' })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Manage' }));
    expect(screen.getByRole('checkbox', { name: 'Available for new enquiries' })).toBeChecked();
    expect(screen.queryByLabelText('Maximum active enquiries')).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('checkbox', { name: 'Available for new enquiries' }));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Save availability' }));
    expect(api).toHaveBeenCalledWith('/counsellor-profiles/1/', { method: 'PATCH', body: { is_available: false } });
  });
  it('renders the immutable assignment reason and actor', async () => {
    vi.mocked(api).mockResolvedValue({ count: 1, next: null, previous: null, results: [
      { id: 'a', lead: 'lead', lead_label: 'LD-001', branch_name: 'Central', version: 2, previous_owner_name: 'Previous owner', new_owner_name: 'New owner', status: 'assigned', reason: 'Workload balanced', actor_name: 'Branch manager', created_at: '2026-10-25T09:00:00Z' },
    ] });
    wrap(<AssignmentsPage />);
    expect(await screen.findByText('Workload balanced')).toBeInTheDocument();
    expect(screen.getByText('Branch manager')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'LD-001' })).toHaveAttribute('href', '/leads/lead');
    expect(screen.queryByRole('button', { name: /edit|delete/i })).not.toBeInTheDocument();
  });
  it('shows a real empty contact state and hides creation for support', async () => {
    vi.mocked(api).mockResolvedValue({ count: 0, next: null, previous: null, results: [] }); wrap(<ContactsPage />);
    expect(await screen.findByText('Your contacts start here')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New contact' })).not.toBeInTheDocument();
  });
  it('shows retryable API failures instead of invented zero data', async () => {
    vi.mocked(api).mockRejectedValue(new Error('Database unavailable')); wrap(<LeadsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByText('No enquiries found')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Create enquiry from a contact/ })).not.toBeInTheDocument();
  });
  it('hides branch configuration from scoped staff and displays it for management', async () => {
    vi.mocked(api).mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    const view = wrap(<BranchesPage />); await screen.findByText('No branches in your scope');
    expect(screen.queryByRole('button', { name: 'Add branch' })).not.toBeInTheDocument(); view.unmount();
    state.user.capabilities.manage_branches = true; wrap(<BranchesPage />);
    expect(await screen.findByRole('button', { name: 'Add branch' })).toBeInTheDocument();
  });
  it('validates login through Django and surfaces a failed sign in', async () => {
    vi.mocked(api).mockRejectedValue(new Error('Invalid credentials.')); wrap(<LoginForm />);
    const user = userEvent.setup(); await user.type(screen.getByLabelText('Username'), 'staff'); await user.type(screen.getByLabelText('Password'), 'invalid'); await user.click(screen.getByRole('button', { name: 'Sign in to your workspace' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid credentials.');
    expect(api).toHaveBeenCalledWith('/auth/login/', { method: 'POST', body: { username: 'staff', password: 'invalid' } });
  });
});
