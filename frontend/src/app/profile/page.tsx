'use client';
import { useUser } from '@/components/providers';
import { useList } from '@/components/data';
import { PageHeader, ErrorState } from '@/components/ui';
import { initials, label } from '@/lib/format';
import type { Branch } from '@/lib/types';
export default function ProfilePage() { const user = useUser(); const branches = useList<Branch>('/branches/'); const name = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username; return <><PageHeader eyebrow="YOUR ACCOUNT" title="My profile" description="Your LearnMore identity and workspace access." /><section className="panel profile-panel"><span className="avatar large">{initials(name)}</span><h2>{name}</h2><dl><dt>Username</dt><dd>{user.username}</dd><dt>Email</dt><dd>{user.email || 'Not provided'}</dd><dt>Role</dt><dd>{label(user.role)}</dd><dt>Scope</dt><dd>{user.capabilities.global_scope ? 'All branches' : branches.data?.results.find(b => b.id === user.branch)?.name || 'Your assigned branch'}</dd></dl>{branches.error && <ErrorState error={branches.error} />}<p className="muted small-text">Contact your administrator to update account details or reset your password.</p></section></>; }
