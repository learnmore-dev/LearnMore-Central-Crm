import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { clearSession } from '@/lib/session';
import { Providers } from '@/components/providers';
import { Shell } from '@/components/shell';
import type { Profile } from '@/lib/types';

vi.mock('next/navigation', () => ({ usePathname: () => '/' }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const profile: Profile = {
  id: 'user', username: 'counsellor', first_name: 'Asha', last_name: '', email: '',
  role: 'counsellor', branch: 'branch',
  capabilities: { global_scope: false, manage_branches: false, sales_write: true, manage_routing: false },
};
beforeEach(() => vi.mocked(api).mockReset());

describe('signing out', () => {
  it.each([
    ['active session', null],
    ['expired session', new ApiError(401, { detail: 'Session expired.' })],
    ['already signed out', new ApiError(403, { detail: 'Authentication credentials were not provided.' })],
  ])('returns to login without an authentication error for an %s', async (_name, error) => {
    vi.mocked(api).mockImplementation(async path => {
      if (path === '/auth/logout/') { if (error) throw error; return null; }
      return profile;
    });
    render(<Providers><Shell><p>Private student records</p></Shell></Providers>);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('button', { name: /Sign in to your workspace/ })).toBeInTheDocument();
    expect(screen.queryByText('Private student records')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(api).toHaveBeenCalledWith('/auth/logout/', { method: 'POST' });
  });

  it('keeps a genuine CSRF rejection visible rather than pretending logout succeeded', async () => {
    vi.mocked(api).mockImplementation(async path => {
      if (path === '/auth/logout/') throw new ApiError(403, { detail: 'CSRF Failed: CSRF token incorrect.' });
      return profile;
    });
    render(<Providers><Shell><p>Private student records</p></Shell></Providers>);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('CSRF Failed');
    expect(screen.getByText('Private student records')).toBeInTheDocument();
  });

  it('prevents a late query response from restoring cached student data after sign-out', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(['session'], profile);
    client.setQueryData(['record', 'existing-student'], { name: 'Private student' });
    let finish!: (value: unknown) => void;
    const request = client.fetchQuery({ queryKey: ['list', 'contacts'],
      queryFn: () => new Promise(resolve => { finish = resolve; }) });
    const cancelled = request.catch(() => undefined);
    await clearSession(client);
    finish({ name: 'Late private response' });
    await cancelled;
    await waitFor(() => expect(client.getQueryData(['session'])).toBeNull());
    expect(client.getQueryData(['record', 'existing-student'])).toBeUndefined();
    expect(client.getQueryData(['list', 'contacts'])).toBeUndefined();
  });
});
