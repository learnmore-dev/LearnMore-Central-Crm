import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { LeadForm } from '@/components/lead-form';
import { LearningPreferenceFields, learningPreferences } from '@/components/learning-preferences';

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => navigation }));
vi.mock('@/components/providers', () => ({ useUser: () => ({ branch: 'branch' }) }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const paged = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });
function wrap(child: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{child}</QueryClientProvider>); }
beforeEach(() => {
  navigation.push.mockReset(); vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/education/preferred-branches/') return [{ id: 'branch', name: 'Central' }, { id: 'preferred', name: 'BTM Layout' }];
    if (path === '/branches/') return paged([{ id: 'branch', name: 'Central', is_active: true }]);
    if (options?.method === 'POST') return { id: 'enquiry' };
    return {};
  });
});

describe('unified enquiry capture', () => {
  it('keeps multiple interests, switches the primary and selects a fallback when it is removed', async () => {
    function Example() { const [value, setValue] = useState(learningPreferences(null, 'Python')); return <LearningPreferenceFields value={value} onChange={setValue} />; }
    wrap(<Example />); const user = userEvent.setup();
    fireEvent.change(screen.getByRole('combobox', { name: 'Additional course interest' }), { target: { value: 'Data Science' } });
    await user.click(screen.getByRole('button', { name: 'Add course' }));
    expect(within(screen.getByRole('list', { name: 'Selected course interests' })).getAllByRole('listitem')).toHaveLength(2);
    await user.click(screen.getByRole('button', { name: 'Make primary' }));
    expect(screen.getByRole('combobox', { name: 'Course name' })).toHaveValue('Data Science');
    await user.click(screen.getByRole('button', { name: 'Remove Data Science' }));
    expect(screen.getByRole('combobox', { name: 'Course name' })).toHaveValue('Python');
  });

  it('saves candidate, course preferences, city and follow-up in a single request', async () => {
    wrap(<LeadForm onClose={vi.fn()} />); const user = userEvent.setup();
    await screen.findByRole('option', { name: 'BTM Layout' });
    await user.type(screen.getByLabelText('Candidate name'), 'Candidate');
    await user.type(screen.getByLabelText('Mobile'), '9876543210');
    fireEvent.change(screen.getByRole('combobox', { name: 'Course name' }), { target: { value: 'Python' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Additional course interest' }), { target: { value: 'Data Science' } });
    await user.click(screen.getByRole('button', { name: 'Add course' }));
    await user.selectOptions(screen.getByLabelText('Training mode'), 'classroom');
    await user.type(screen.getByLabelText('Candidate city'), 'Mysuru');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Preferred training branch' }), 'preferred');
    await user.selectOptions(screen.getByLabelText('Enquiry source'), 'whatsapp');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Next action (optional)' }), 'Call candidate');
    fireEvent.change(screen.getByLabelText('Deadline (your local time)'), { target: { value: '2026-12-01T11:00' } });
    await user.click(screen.getByRole('button', { name: 'Create enquiry' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/leads/intake/', { method: 'POST', body: {
      candidate: { full_name: 'Candidate', mobile: '9876543210', email: '' }, branch: 'branch', source: 'whatsapp', title: 'Python',
      qualification: { course_interest: 'Python', course_interests: ['Python', 'Data Science'], training_mode: 'classroom', city: 'Mysuru', preferred_branch: 'preferred' },
      next_action: 'Call candidate', next_action_at: new Date('2026-12-01T11:00').toISOString(),
    } }));
    expect(navigation.push).toHaveBeenCalledWith('/leads/enquiry');
  });

  it('retains entered details when a possible duplicate requires review', async () => {
    const initial = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (options?.method === 'POST') throw new ApiError(409, { id: 'review' });
      return initial(path, options);
    });
    wrap(<LeadForm onClose={vi.fn()} />); const user = userEvent.setup();
    await screen.findByRole('option', { name: 'BTM Layout' });
    await user.type(screen.getByLabelText('Candidate name'), 'Existing candidate');
    await user.type(screen.getByLabelText('Mobile'), '9876543210');
    fireEvent.change(screen.getByRole('combobox', { name: 'Course name' }), { target: { value: 'Python' } });
    await user.click(screen.getByRole('button', { name: 'Create enquiry' }));
    expect(await screen.findByText('Possible duplicate — saved for review')).toBeInTheDocument();
    expect(navigation.push).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Review entered details' }));
    expect(screen.getByLabelText('Candidate name')).toHaveValue('Existing candidate');
    expect(screen.getByRole('combobox', { name: 'Course name' })).toHaveValue('Python');
  });
});
