import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { AutomationPage, RuleForm } from '@/components/automation';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const identity = { role: 'branch_manager', branch: 'branch', capabilities: { global_scope: false, sales_write: true } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
const paged = (results: unknown[]) => ({ count: results.length, results, next: null, previous: null });
function wrap(content = <AutomationPage />) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{content}</QueryClientProvider>); }
const starterLibrary = {
  courses: ['Python Full Stack Development', 'Power BI'],
  templates: [{ key: 'all', name: 'LearnMore | IT course enquiry - counselling and course guide', source: 'all', description: 'Counselling, course guidance and a decision review.', callback_minutes: 10, acknowledgement_text: 'Welcome to LearnMore Technologies, {name}.', steps: [{ kind: 'task', title: 'Confirm course interest', delay_minutes: 30 }] }],
};
beforeEach(() => {
  vi.mocked(api).mockReset(); identity.role = 'branch_manager';
  vi.mocked(api).mockImplementation(async path => path === '/automation/rules/templates/' ? starterLibrary : paged([]));
});

describe('CRM automation', () => {
  it('clearly labels simulation mode and shows empty rules', async () => {
    wrap();
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
    identity.role = 'counsellor'; wrap();
    await screen.findByText('No automation rules yet');
    expect(screen.queryByRole('button', { name: 'Create rule' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enroll existing enquiry' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Install starter rules' })).not.toBeInTheDocument();
    expect(await screen.findByText('LearnMore IT course guide')).toBeInTheDocument();
  });

  it('shows LearnMore rule previews and a searchable course catalogue', async () => {
    wrap();
    const user = userEvent.setup();
    expect(await screen.findByText('IT course enquiry - counselling and course guide')).toBeInTheDocument();
    await user.click(screen.getByText('View sequence & message preview'));
    expect(screen.getByText('Welcome to LearnMore Technologies, {name}.')).toBeVisible();
    await user.click(screen.getByText(/Browse full course catalogue/));
    await user.type(screen.getByRole('searchbox', { name: 'Search course catalogue' }), 'Python Full Stack');
    const list = screen.getByRole('list', { name: 'Course catalogue' });
    expect(within(list).getByText('Python Full Stack Development')).toBeInTheDocument();
    expect(within(list).queryByText('Advanced Excel')).not.toBeInTheDocument();
  });

  it('installs and enables starter rules for the selected branch', async () => {
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === '/automation/rules/templates/') return starterLibrary;
      if (path === '/branches/') return paged([{ id: 'branch', name: 'Central', is_active: true }]);
      if (options?.method) return { created: 5, enabled: 5, preserved: 0, conflicts: [] };
      return paged([]);
    });
    wrap(); const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Install starter rules' }));
    await screen.findByRole('option', { name: 'Central' });
    expect(screen.getByRole('checkbox', { name: 'Enable rules for new enquiries' })).not.toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Enable rules for new enquiries' }));
    await user.click(screen.getByRole('button', { name: 'Install & enable rules' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/automation/rules/install-starters/', { method: 'POST', body: { branch: 'branch', enable: true } }));
    expect(await screen.findByRole('status')).toHaveTextContent('5 rules added');
    expect(screen.getByRole('status')).toHaveTextContent('5 enabled');
  });

  it('copies the candidate course guide', async () => {
    wrap(); const user = userEvent.setup();
    const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    await user.click(await screen.findByRole('button', { name: 'Copy course list' }));
    expect(copy).toHaveBeenCalledWith(expect.stringContaining('Python Full Stack Development'));
    expect(copy).toHaveBeenCalledWith(expect.stringContaining('LearnMore Technologies'));
    expect(await screen.findByRole('status')).toHaveTextContent('Course list copied');
  });

  it('shows API failures with a retry control', async () => {
    vi.mocked(api).mockImplementation(async path => { if (path === '/automation/rules/templates/') return starterLibrary; throw new Error('Automation unavailable'); }); wrap();
    expect(await screen.findByRole('alert')).toHaveTextContent('Automation unavailable');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
