'use client';
import { CourseField } from '@/components/course-field';
import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { Branch, Lead } from '@/lib/types';
import { useList } from './data';
import { useUser } from './providers';
import { Field, FormError } from './ui';
export function LeadForm({ contact, onClose }: { contact: string; onClose: () => void }) {
  const user = useUser(); const client = useQueryClient(); const router = useRouter(); const branches = useList<Branch>('/branches/');
  const [title, setTitle] = useState(''); const [branch, setBranch] = useState(user.branch || ''); const [action, setAction] = useState(''); const [deadline, setDeadline] = useState('');
  const create = useMutation({ mutationFn: () => api<Lead>('/leads/', { method: 'POST', body: { contact, title, branch,
    ...(action.trim() ? { next_action: action, next_action_at: new Date(deadline).toISOString() } : {}) } }),
    onSuccess: lead => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); router.push(`/leads/${lead.id}`); } });
  function submit(event: FormEvent) { event.preventDefault(); create.mutate(); }
  return <form onSubmit={submit} className="form-stack"><CourseField required value={title} onChange={setTitle} /><Field title="Branch"><select required value={branch} onChange={e => setBranch(e.target.value)}><option value="">Choose branch</option>{branches.data?.results.filter(b => b.is_active).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field><div className="notice">An eligible owner will be preserved or selected by branch rotation. If nobody is available, the enquiry stays in the unassigned queue.</div><Field title="Next action (optional)" hint="Leave blank to use the branch’s new-enquiry deadline."><input maxLength={500} value={action} onChange={e => setAction(e.target.value)} /></Field>{action.trim() && <Field title="Deadline (your local time)"><input type="datetime-local" required value={deadline} onChange={e => setDeadline(e.target.value)} /></Field>}<FormError error={branches.error || create.error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={create.isPending || !branch}>{create.isPending ? 'Creating…' : 'Create enquiry'}</button></div></form>;
}
