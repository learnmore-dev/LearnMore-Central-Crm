import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { EmployeeAdmin, EmployeeForm, EmployeePasswordForm, type ManagedEmployee } from '@/components/employee-admin';

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const identity = { id: 'admin', role: 'super_admin', capabilities: { manage_users: true, global_scope: true } };
vi.mock('@/components/providers', () => ({ useUser: () => identity }));
const employee: ManagedEmployee = { id: 'employee', username: 'asha.kn', first_name: 'Asha', last_name: 'K', email: '', role: 'counsellor', branch: 'branch', branch_name: 'Kalyan Nagar', is_active: true, routing_enabled: false, capacity: 50, active_enquiries: 0, protected_account: false, date_joined: '2026-11-02T10:00:00+05:30', last_login: null };
const paged = (results: unknown[]) => ({ count: results.length, results, next: null, previous: null });
function wrap(child: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{child}</QueryClientProvider>); }
beforeEach(() => {
  identity.capabilities.manage_users = true; vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (options?.method) return employee;
    if (path.startsWith('/branches/')) return paged([{ id: 'branch', name: 'Kalyan Nagar', is_active: true }]);
    if (path === '/admin/employees/summary/') return { total: 1, active: 1, inactive: 0, assignment_ready: 0 };
    if (path.startsWith('/admin/access-events/')) return paged([{ id: 1, actor_name: 'admin', target_name: 'asha.kn', action: 'password_reset', detail: { self_service: false }, created_at: '2026-11-02T10:00:00+05:30' }]);
    return paged([employee]);
  });
});

describe('employee administration', () => {
  it('blocks the admin workspace for staff without employee-management capability', () => {
    identity.capabilities.manage_users = false; wrap(<EmployeeAdmin />);
    expect(screen.getByText('Administrator access required')).toBeInTheDocument();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
  it('creates an intern with a branch and password without routing or system privileges', async () => {
    const close = vi.fn(); wrap(<EmployeeForm close={close} />); const user = userEvent.setup();
    await user.type(screen.getByLabelText('First name'), 'Nisha');
    await user.type(screen.getByLabelText('Username'), 'nisha.kn');
    await user.selectOptions(screen.getByLabelText('CRM role'), 'intern');
    await user.selectOptions(await screen.findByLabelText('Assigned branch'), 'branch');
    await user.type(screen.getByLabelText('Initial password'), 'Meadow!Window!Velvet!2026');
    expect(screen.queryByText('Include in automatic enquiry assignment')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create employee' }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    const call = vi.mocked(api).mock.calls.find(([, options]) => options?.method === 'POST');
    expect(call?.[1]?.body).toMatchObject({ username: 'nisha.kn', role: 'intern', branch: 'branch', is_active: true, can_receive_leads: false, password: 'Meadow!Window!Velvet!2026' });
    expect(call?.[1]?.body).not.toHaveProperty('is_superuser');
  });
  it('keeps an employee draft open through dialog clicks and background refreshes', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><EmployeeAdmin /></QueryClientProvider>);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Add employee' }));
    const dialog = screen.getByRole('dialog', { name: 'Create employee account' });
    await user.type(screen.getByLabelText('First name'), 'Nisha');
    await user.type(screen.getByLabelText('Username'), 'nisha.kn');
    fireEvent.click(dialog);
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute('open');
    expect(screen.getByLabelText('First name')).toHaveValue('Nisha');
    await act(async () => { await client.invalidateQueries(); });
    expect(screen.getByRole('dialog', { name: 'Create employee account' })).toHaveAttribute('open');
    expect(screen.getByLabelText('Username')).toHaveValue('nisha.kn');
    await user.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  });

  it('requires matching passwords before resetting an employee password', async () => {
    const close = vi.fn(); wrap(<EmployeePasswordForm employee={employee} close={close} />); const user = userEvent.setup();
    const update = screen.getByRole('button', { name: 'Update password' }); expect(update).toBeDisabled();
    await user.type(screen.getByLabelText('New password'), 'Meadow!Window!Velvet!2026');
    await user.type(screen.getByLabelText('Confirm new password'), 'Different!Password!2026');
    expect(update).toBeDisabled(); expect(screen.getByText('Passwords do not match.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Confirm new password')); await user.type(screen.getByLabelText('Confirm new password'), 'Meadow!Window!Velvet!2026');
    await user.click(update);
    await waitFor(() => expect(api).toHaveBeenCalledWith('/admin/employees/employee/reset-password/', { method: 'POST', body: { password: 'Meadow!Window!Velvet!2026' } }));
    expect(close).toHaveBeenCalled();
  });
  it('provides role guidance, employee actions and access history', async () => {
    wrap(<EmployeeAdmin />); const user = userEvent.setup();
    expect(await screen.findByText('Asha K')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset password' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Roles & permissions' }));
    expect(screen.getByRole('heading', { name: 'Intern' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Admin' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Access history' }));
    expect(await screen.findByText('asha.kn')).toBeInTheDocument();
    expect(screen.getByText('password reset')).toBeInTheDocument();
  });
  it('prevents the current administrator from editing their own role or active access', async () => {
    wrap(<EmployeeForm employee={{ ...employee, id: 'admin', role: 'super_admin', branch: null }} close={vi.fn()} />);
    expect(screen.getByLabelText('CRM role')).toBeDisabled();
    expect(screen.getByLabelText('Assigned branch')).toBeDisabled();
    expect(screen.queryByText('Account active — allow sign-in')).not.toBeInTheDocument();
  });
});
