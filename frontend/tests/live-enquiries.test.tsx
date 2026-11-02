import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import LiveEnquiriesPage from '@/app/live-enquiries/page';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const entry = { key: 'call:one', source: 'call', source_label: 'Incoming call · missed', name: 'Call Student', phone: '+919876543210',
  title: 'Phone enquiry', preview: 'Please call back', branch: 'branch', branch_name: 'Central', status: 'needs_enquiry', owner_name: null,
  lead: null, lead_label: null, contact: null, received_at: '2026-10-25T09:00:00Z', activity_at: '2026-10-25T09:00:00Z', target: 'call', target_id: '+919876543210' };
const website = { ...entry, key: 'website:two', source: 'website', source_label: 'learnmoretech.in', name: 'Website Student', title: 'Python',
  status: 'new', owner_name: 'Counsellor', lead: 'lead', lead_label: 'LM-L-001', target: 'website', target_id: 'submission' };
const data = (results: Array<typeof entry | typeof website> = [entry]) => ({ count: results.length, page: 1, page_size: 25, has_next: false, server_time: '2026-10-25T09:00:15Z',
  sources: ['website', 'call', 'whatsapp', 'manual'], totals: { all: results.length, unassigned: 0, review: 0, awaiting_reply: 0, needs_enquiry: 1, new: 0 },
  source_totals: { website: 0, call: 1, whatsapp: 0, manual: 0 }, whatsapp_mode: 'mock', results });
function mockReads(read: () => unknown) { vi.mocked(api).mockImplementation(async path => path.startsWith('/branches/') ? { count: 1, next: null, previous: null, results: [{ id: 'branch', name: 'Central' }] } : read()); }
function wrap() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><LiveEnquiriesPage /></QueryClientProvider>); }
beforeEach(() => { vi.mocked(api).mockReset(); });
afterEach(() => { vi.useRealTimers(); });

describe('unified live enquiry monitor', () => {
  it('shows multiple sources together with links to the right workflow', async () => {
    mockReads(() => data([entry, website])); wrap();
    expect(await screen.findByText('Call Student')).toBeInTheDocument();
    expect(screen.getByText('Website Student')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open enquiry' })).toHaveAttribute('href', '/leads/lead');
    expect(screen.getByRole('link', { name: 'Open call' })).toHaveAttribute('href', '/calls?search=%2B919876543210');
    expect(screen.getByText('Live monitoring')).toBeInTheDocument();
  });
  it('automatically loads arrivals every five seconds and supports pausing', async () => {
    vi.useFakeTimers(); let reads = 0;
    mockReads(() => ++reads === 1 ? data() : data([entry, website])); wrap();
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    expect(screen.getByText('Call Student')).toBeInTheDocument();
    expect(screen.queryByText('Website Student')).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(5100); });
    expect(screen.getByText('Website Student')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Pause live updates' }));
    const pausedAt = reads;
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(reads).toBe(pausedAt);
    expect(screen.getByText('Monitoring paused')).toBeInTheDocument();
  });
  it('shows retryable errors without pretending that zero enquiries were returned', async () => {
    mockReads(() => { throw new Error('Feed unavailable'); }); wrap();
    expect(await screen.findByRole('alert')).toHaveTextContent('Feed unavailable');
    expect(screen.getByText('Updates failed')).toBeInTheDocument();
    expect(screen.queryByText('No enquiries in this view')).not.toBeInTheDocument();
  });
  it('passes source and status filters to the backend', async () => {
    mockReads(() => data()); wrap(); await screen.findByText('Call Student'); const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('Enquiry state'), 'needs_enquiry');
    expect(api).toHaveBeenCalledWith(expect.stringContaining('status=needs_enquiry'), expect.any(Object));
    await user.click(screen.getByRole('button', { name: /^Website forms/ }));
    expect(api).toHaveBeenCalledWith(expect.stringContaining('source=website'), expect.any(Object));
  });
});
