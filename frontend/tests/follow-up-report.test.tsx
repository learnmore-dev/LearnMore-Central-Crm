import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Workday } from '@/components/workday';
import { FollowUpReport } from '@/components/follow-up-report';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const identity = { role: 'counsellor', capabilities: { global_scope: false, sales_write: true } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
const totals = { assigned: 3, due: 2, pending: 1, overdue: 1, completed_on_time: 0, completed_late: 0, missed_deadline: 1, no_contact: 1, unanswered: 1 };
const report = { server_time: '2026-11-02T09:00:00+05:30', totals, counsellors: [{ owner: 'owner', name: 'Asha', ...totals }], count: 1, has_next: false, results: [{ origin: 'followups', task: 'task', name: 'Student A', course: 'Python', title: 'Call student', owner: 'Asha', category: 'overdue', due_at: '2026-11-02T08:00:00+05:30', delay_minutes: 60, target: '/leads/lead', status: 'pending', completed_at: null, resolution: '' }] };
function wrap(child: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{child}</QueryClientProvider>); }
beforeEach(() => { identity.role = 'counsellor'; vi.mocked(api).mockReset(); vi.mocked(api).mockImplementation(async path => path.startsWith('/branches/') ? { count: 0, results: [] } : report); });

describe('counsellor reminders and accountability', () => {
  it('connects the personal daily queue to the unified workday endpoint', async () => {
    vi.mocked(api).mockImplementation(async path => path.startsWith('/education/workday/') ? { server_time: report.server_time, counts: { today: 1, overdue: 1, upcoming: 0, all: 1 }, count: 1, has_next: false, results: [{ id: 'task', origin: 'demo', kind: 'attendance', name: 'Student B', title: 'Record attendance', due_at: report.results[0].due_at, status: 'pending', target: '/demos?lead=lead' }] } : path.startsWith('/branches/') ? { count: 0, results: [] } : report);
    wrap(<Workday />);
    expect(await screen.findByText('Record attendance')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open workspace/ })).toHaveAttribute('href', '/demos?lead=lead');
    expect(screen.queryByRole('link', { name: /Team report/ })).not.toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('/education/workday/') && !path.includes('team=true'))).toBe(true);
  });
  it('shows personal evidence and filters unanswered calls separately', async () => {
    wrap(<FollowUpReport embedded />);
    expect(await screen.findByText('Student A')).toBeInTheDocument();
    await userEvent.setup().selectOptions(screen.getByLabelText('Report category'), 'unanswered');
    expect(await screen.findByText(/This is a student response outcome/)).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('category=unanswered') && path.includes('team=false'))).toBe(true));
  });
  it('restricts team reporting and exposes counsellor filters to managers', async () => {
    const view = wrap(<FollowUpReport team />);
    expect(screen.getByText('Manager access required')).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('team=true'))).toBe(false);
    view.unmount(); identity.role = 'branch_manager'; wrap(<FollowUpReport team />);
    expect(await screen.findByRole('option', { name: 'Asha' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Counsellor scorecard' })).toBeInTheDocument();
    await userEvent.setup().selectOptions(screen.getByLabelText('Report counsellor'), 'owner');
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('team=true') && path.includes('owner=owner'))).toBe(true));
  });
});
