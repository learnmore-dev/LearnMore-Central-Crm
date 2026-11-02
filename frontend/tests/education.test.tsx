import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Lead } from '@/lib/types';
import { QualificationForm, type Qualification } from '@/components/student-journey';
import { DemoBookingForm, DemosPage } from '@/components/demos';
import AttentionPage from '@/app/attention/page';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const identity = { role: 'branch_manager', capabilities: { global_scope: false, sales_write: true } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
const paged = (results: unknown[]) => ({ count: results.length, results, next: null, previous: null });
function wrap(child: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{child}</QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); identity.role = 'branch_manager'; });

describe('Edtech counselling workflow', () => {
  it('saves qualification without returning read-only API metadata', async () => {
    vi.mocked(api).mockResolvedValue({});
    const lead = { id: 'lead', title: 'Python' } as Lead;
    const data = { lead: 'lead', updated_at: null, course_interest: '', background: 'unknown', training_mode: 'undecided', preferred_location: '', preferred_schedule: 'undecided', joining_timeline: 'undecided', readiness: 'exploring', notes: '', missing_fields: ['course_interest'] } as Qualification;
    wrap(<QualificationForm lead={lead} data={data} onClose={vi.fn()} />); const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('Training Mode'), 'online');
    await user.selectOptions(screen.getByLabelText('Joining Timeline'), 'month');
    await user.click(screen.getByRole('button', { name: 'Save qualification' }));
    const request = vi.mocked(api).mock.calls[0][1]!;
    expect(request.body).toMatchObject({ course_interest: 'Python', training_mode: 'online', joining_timeline: 'month' });
    expect(request.body).not.toHaveProperty('lead');
    expect(request.body).not.toHaveProperty('updated_at');
  });
  it('books a demo with an idempotency key and shows staff-only reminder wording', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => options?.method ? {} : paged([{ id: 'lead', title: 'Python', contact_name: 'Student', can_edit: true, status: 'new' }]));
    const close = vi.fn(); wrap(<DemoBookingForm onClose={close} />); const user = userEvent.setup();
    await screen.findByRole('option', { name: 'Student · Python' });
    await user.selectOptions(screen.getByLabelText('Student enquiry'), 'lead');
    await user.type(screen.getByLabelText('Campus / classroom'), 'Marathahalli room 1');
    await user.type(screen.getByLabelText('Demo time (your local time)'), '2026-12-01T10:00');
    await user.click(screen.getByRole('button', { name: 'Book demo' }));
    expect(api).toHaveBeenCalledWith('/education/demos/', expect.objectContaining({ method: 'POST', body: expect.objectContaining({ lead: 'lead', course: 'Python', duration_minutes: 60, client_key: expect.any(String) }) }));
    expect(close).toHaveBeenCalled();
  });
  it('records no-show explicitly with a version and outcome', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => options?.method ? {} : paged([{ id: 'demo', lead: 'lead', name: 'Student', course: 'Python', owner_name: 'Counsellor', branch_name: 'Central', mode: 'online', location: 'Meeting details', starts_at: '2026-10-25T10:00:00Z', duration_minutes: 60, status: 'scheduled', version: 2 }]));
    wrap(<DemosPage />); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Did not attend' }));
    await user.type(screen.getByLabelText('Outcome / reason'), 'Student requested a new date');
    await user.click(screen.getByRole('button', { name: 'Save demo outcome' }));
    expect(api).toHaveBeenCalledWith('/education/demos/demo/change/', { method: 'POST', body: { action: 'no_show', version: 2, reason: 'Student requested a new date' } });
  });
  it('shows worker failure and real manager attention counts', async () => {
    vi.mocked(api).mockImplementation(async path => path === '/branches/' ? paged([]) : { server_time: '2026-10-26T10:00:00Z', counts: { demo_attention: 2 }, alerts: { demo_attention: [{ name: 'Student', title: 'Record attendance', target: '/demos?lead=lead', due_at: '2026-10-26T09:00:00Z' }] }, job: { last_attempt_at: '2026-10-26T10:00:00Z', last_success_at: null, error_code: 'demos:RuntimeError', consecutive_failures: 1, stale: false }, source_results: [] });
    wrap(<AttentionPage />);
    expect(await screen.findByText('Automation needs review — retry pending')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Student: Record attendance/ })).toHaveAttribute('href', '/demos?lead=lead');
    expect(screen.getByText('2')).toBeInTheDocument();
  });
  it('restricts monitoring for counsellors and reports API failures', async () => {
    identity.role = 'counsellor'; vi.mocked(api).mockResolvedValue(paged([]));
    const first = wrap(<AttentionPage />);
    expect(screen.getByText('Manager access required')).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining('/education/attention/'), expect.anything());
    first.unmount(); identity.role = 'branch_manager'; vi.mocked(api).mockRejectedValue(new Error('Demo service unavailable'));
    wrap(<DemosPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Demo service unavailable');
  });
});
