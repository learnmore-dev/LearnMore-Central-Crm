import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { AutomationPage, RuleForm } from '@/components/automation';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const identity = { role: 'branch_manager', branch: 'branch', capabilities: { global_scope: false, sales_write: true } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
const paged = (results: unknown[]) => ({ count: results.length, results, next: null, previous: null });
function wrap(content = <AutomationPage />) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{content}</QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); identity.role = 'branch_manager'; });

describe('CRM automation', () => {
  it('clearly labels simulation mode and shows empty rules', async () => {
    vi.mocked(api).mockResolvedValue(paged([])); wrap();
    expect(await screen.findByText('No automation rules yet')).toBeInTheDocument();
    expect(screen.getByText('Simulation mode · No messages sent')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create rule' })).toBeInTheDocument();
  });
  it('creates disabled rules with an editable sequence and mock acknowledgement', async () => {
    vi.mocked(api).mockImplementation(async (path, options) => options?.method ? {} : path === '/branches/' ? paged([{ id: 'branch', name: 'Central' }]) : paged([]));
    const close = vi.fn(); wrap(<RuleForm onClose={close} />); const user = userEvent.setup();
    await screen.findByRole('option', { name: 'Central' });
    expect(screen.getByLabelText('Enable for new arrivals (mock only)')).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Remove step 4' }));
    await user.click(screen.getByRole('button', { name: 'Save rule' }));
    expect(api).toHaveBeenCalledWith('/automation/rules/', expect.objectContaining({ method: 'POST', body: expect.objectContaining({ branch: 'branch', is_active: false, steps: expect.any(Array) }) }));
    expect(close).toHaveBeenCalled();
  });
  it('shows callback work, record links and records an outcome', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => options?.method ? {} : paged([{ id: 'task', title: 'Callback missed caller', name: 'Student', phone: '+919876543210', status: 'pending', due_at: '2026-10-26T10:00:00Z', assignee_name: 'owner', call: 'call', lead: null, overdue: false }]));
    wrap(<AutomationPage initialTab="work" />); const user = userEvent.setup();
    expect(await screen.findByText('Callback missed caller')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review call / create enquiry' })).toHaveAttribute('href', '/calls?search=%2B919876543210');
    await user.click(screen.getByRole('button', { name: 'Complete' }));
    await user.type(screen.getByLabelText('Outcome'), 'Discussed Python course');
    await user.click(screen.getByRole('button', { name: 'Complete task' }));
    expect(api).toHaveBeenCalledWith(expect.stringContaining('/automation/work/task/complete/'), expect.objectContaining({ method: 'POST', body: { resolution: 'Discussed Python course' } }));
  });
  it('restricts configuration controls for counsellors', async () => {
    identity.role = 'counsellor'; vi.mocked(api).mockResolvedValue(paged([])); wrap();
    await screen.findByText('No automation rules yet');
    expect(screen.queryByRole('button', { name: 'Create rule' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enroll existing enquiry' })).not.toBeInTheDocument();
  });
  it('shows API failures with a retry control', async () => {
    vi.mocked(api).mockRejectedValue(new Error('Automation unavailable')); wrap();
    expect(await screen.findByRole('alert')).toHaveTextContent('Automation unavailable');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
