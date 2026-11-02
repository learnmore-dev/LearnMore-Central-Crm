'use client';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import type { Profile } from '@/lib/types';
import { LoginForm } from './login';
import { ErrorState, Loading } from './ui';
const UserContext = createContext<Profile | null>(null);
export function useUser() { const user = useContext(UserContext); if (!user) throw new Error('Sign in to access the CRM.'); return user; }
function Session({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const session = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => api<Profile | null>('/auth/me/', { signal }), retry: false });
  useEffect(() => {
    const expire = () => { void client.cancelQueries(); client.removeQueries({ predicate: q => q.queryKey[0] !== 'session' }); client.setQueryData(['session'], null); };
    window.addEventListener('crm-session-expired', expire);
    return () => window.removeEventListener('crm-session-expired', expire);
  }, [client]);
  if (session.isPending) return <main className="auth-loading"><Loading text="Opening your workspace…" /></main>;
  if (!session.data) {
    if (session.error && !(session.error instanceof ApiError && [401, 403].includes(session.error.status))) return <main className="auth-loading"><ErrorState error={session.error} retry={() => void session.refetch()} /></main>;
    return <LoginForm />;
  }
  return <UserContext.Provider value={session.data}>{children}</UserContext.Provider>;
}
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000,
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500) }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Session>{children}</Session></QueryClientProvider>;
}
