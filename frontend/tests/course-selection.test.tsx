import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { CourseField } from '@/components/course-field';
import { LeadForm } from '@/components/lead-form';

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => navigation }));
vi.mock('@/components/providers', () => ({ useUser: () => ({ branch: 'branch' }) }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
beforeEach(() => { vi.mocked(api).mockReset(); navigation.push.mockReset(); });

describe('student course selection', () => {
  it('offers supplied courses while preserving an existing custom title', () => {
    const changed = vi.fn();
    render(<CourseField value="Existing student course" onChange={changed} />);
    const input = screen.getByRole('combobox', { name: 'Course name' });
    expect(input).toHaveValue('Existing student course');
    const list = document.getElementById(input.getAttribute('list')!)!;
    const names = [...list.querySelectorAll('option')].map(option => option.value);
    expect(names).toContain('Python Full Stack Development');
    expect(names).toContain('Java Full Stack Development');
    expect(names).toContain('.NET');
    expect(names).not.toContain('No Response');
    expect(names).not.toContain('Select Program');
    expect(changed).not.toHaveBeenCalled();
  });

  it('gives simultaneously open course fields separate accessible lists', () => {
    render(<><CourseField title="Course name" value="" onChange={vi.fn()} />
      <CourseField title="Demo course" value="" onChange={vi.fn()} /></>);
    const fields = screen.getAllByRole('combobox');
    expect(fields[0].getAttribute('list')).not.toBe(fields[1].getAttribute('list'));
    expect(fields[0].getAttribute('aria-describedby')).not.toBe(fields[1].getAttribute('aria-describedby'));
  });

  it('saves the chosen course on the student enquiry through the existing API', async () => {
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === '/leads/' && options?.method === 'POST') return { id: 'new-enquiry' };
      return { count: 1, next: null, previous: null, results: [{ id: 'branch', name: 'Central', is_active: true }] };
    });
    const close = vi.fn();
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LeadForm contact="student-contact" onClose={close} />
    </QueryClientProvider>);
    await within(screen.getByLabelText('Branch')).findByRole('option', { name: 'Central' }, { timeout: 3000 });
    const user = userEvent.setup();
    // A browser-native datalist selection raises the same change as typing.
    fireEvent.change(screen.getByRole('combobox', { name: 'Course name' }), { target: { value: 'Python Full Stack Development' } });
    await user.click(screen.getByRole('button', { name: 'Create enquiry' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('/leads/', {
      method: 'POST', body: { contact: 'student-contact', title: 'Python Full Stack Development', branch: 'branch' },
    }));
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith('/leads/new-enquiry'));
    expect(close).toHaveBeenCalled();
  });
});
