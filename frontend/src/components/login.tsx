'use client';
import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowUpRight, Layers3, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import type { Profile } from '@/lib/types';
import { Field, FormError } from './ui';
export function LoginForm() {
  const client = useQueryClient();
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const login = useMutation({ mutationFn: () => api<Profile>('/auth/login/', { method: 'POST', body: { username, password } }),
    onSuccess: profile => { client.removeQueries({ predicate: q => q.queryKey[0] !== 'session' }); client.setQueryData(['session'], profile); setPassword(''); } });
  function submit(event: FormEvent) { event.preventDefault(); login.mutate(); }
  return <main className="login-page"><section className="login-brand"><div className="brand"><span className="brand-mark"><Layers3 size={25} /></span><span>LearnMore<span className="brand-sub">CONNECT</span></span></div><div className="login-intro"><span className="eyebrow">Every conversation. A new possibility.</span><h1>Help ambition<br />find its next step.</h1><p>One workspace for your students, your team and every opportunity to learn.</p><div className="branch-pills"><span>Marathahalli</span><span>BTM Layout</span><span>Kalyan Nagar</span></div></div><span className="login-foot">LearnMore Technologies · Bengaluru</span></section><section className="login-panel"><form onSubmit={submit} className="login-form"><span className="eyebrow">YOUR WORKSPACE AWAITS</span><h2>Welcome back.</h2><p>Sign in to LearnMore Connect.</p><Field title="Username"><input autoComplete="username" required maxLength={150} value={username} onChange={e => setUsername(e.target.value)} autoFocus /></Field><Field title="Password"><input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></Field><FormError error={login.error} /><button className="button primary" disabled={login.isPending}>{login.isPending ? 'Signing in…' : 'Sign in to your workspace'}<ArrowUpRight size={18} /></button><p className="login-security"><ShieldCheck size={16} /> Secure access for LearnMore staff</p><p className="muted small-text">Need access or a password reset? Contact your administrator.</p></form></section></main>;
}
