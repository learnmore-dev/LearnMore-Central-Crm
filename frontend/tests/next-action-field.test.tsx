import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NextActionField, nextActions } from '@/components/next-action-field';
import { LeadForm } from '@/components/lead-form';
import { api } from '@/lib/api';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/components/providers', () => ({ useUser: () => ({ branch: 'branch' }) }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));

function Example({ initial = '', required = false }: { initial?: string; required?: boolean }) {
  const [value, setValue] = useState(initial);
  return <NextActionField value={value} onChange={setValue} required={required} />;
}

describe('next-action choices', () => {
  it('offers ten predefined actions without asking counsellors to type', async () => {
    const changed = vi.fn();
    render(<NextActionField required value="" onChange={changed} />);
    const select = screen.getByRole('combobox', { name: 'Next action' });
    expect(nextActions).toHaveLength(10);
    expect(select).toBeInvalid();
    await userEvent.setup().selectOptions(select, 'Schedule a demo');
    expect(changed).toHaveBeenCalledWith('Schedule a demo');
    expect(screen.queryByLabelText('Custom next action')).not.toBeInTheDocument();
  });

  it('preserves existing custom actions and remembers custom text when switching options', async () => {
    render(<Example initial="Call candidate after their exam" />);
    const user = userEvent.setup();
    const select = screen.getByRole('combobox', { name: 'Next action' });
    expect(screen.getByLabelText('Custom next action')).toHaveValue('Call candidate after their exam');
    await user.selectOptions(select, 'Send course syllabus');
    expect(select).toHaveValue('Send course syllabus');
    expect(screen.queryByLabelText('Custom next action')).not.toBeInTheDocument();
    await user.selectOptions(select, '__custom__');
    expect(screen.getByLabelText('Custom next action')).toHaveValue('Call candidate after their exam');
  });

  it('requires text for a custom choice and permits returning to the optional default', async () => {
    render(<Example />); const user = userEvent.setup();
    const select = screen.getByRole('combobox', { name: 'Next action' });
    await user.selectOptions(select, '__custom__');
    const input = screen.getByLabelText('Custom next action');
    expect(input).toBeInvalid();
    expect(input).toHaveAttribute('maxLength', '500');
    await user.type(input, 'Discuss weekend batch');
    expect(input).toBeValid();
    await user.selectOptions(select, '');
    expect(select).toHaveValue('');
    expect(select).toBeValid();
    expect(screen.queryByLabelText('Custom next action')).not.toBeInTheDocument();
  });

  it('saves a selected action and deadline through the existing enquiry API', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => options?.method
      ? { id: 'new-enquiry' }
      : { count: 1, next: null, previous: null, results: [{ id: 'branch', name: 'Central', is_active: true }] });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><LeadForm contact="contact" onClose={vi.fn()} /></QueryClientProvider>);
    const user = userEvent.setup();
    await screen.findByRole('option', { name: 'Central' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Course name' }), { target: { value: 'Python' } });
    expect(screen.queryByLabelText('Deadline (your local time)')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Next action (optional)' }), 'Schedule a demo');
    const deadline = screen.getByLabelText('Deadline (your local time)');
    expect(deadline).toBeRequired();
    fireEvent.change(deadline, { target: { value: '2026-12-01T11:00' } });
    await user.click(screen.getByRole('button', { name: 'Create enquiry' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/leads/', {
      method: 'POST', body: { contact: 'contact', title: 'Python', branch: 'branch', source: 'manual', qualification: { course_interest: 'Python', course_interests: ['Python'], training_mode: 'undecided', city: '', preferred_branch: null }, next_action: 'Schedule a demo', next_action_at: new Date('2026-12-01T11:00').toISOString() },
    }));
  });
});
