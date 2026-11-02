'use client';
import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api, ApiError } from '@/lib/api';
import type { Branch, Contact, Review } from '@/lib/types';
import { useList } from './data';
import { useUser } from './providers';
import { Field, FormError } from './ui';
export function ContactForm({ onClose }: { onClose: () => void }) {
  const user = useUser(); const client = useQueryClient(); const router = useRouter(); const branches = useList<Branch>('/branches/');
  const [name, setName] = useState(''); const [phone, setPhone] = useState(''); const [email, setEmail] = useState(''); const [branch, setBranch] = useState(user.branch || ''); const [source, setSource] = useState('manual');
  const [review, setReview] = useState<Review | null>(null);
  const create = useMutation({ mutationFn: () => api<Contact>('/contacts/', { method: 'POST', body: { full_name: name, branch, source,
    identifiers: [...(phone.trim() ? [{ kind: 'phone', value: phone }] : []), ...(email.trim() ? [{ kind: 'email', value: email }] : [])] } }),
    onSuccess: contact => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); router.push(`/contacts/${contact.id}`); },
    onError: error => { if (error instanceof ApiError && error.status === 409) setReview(error.data as Review); } });
  function submit(event: FormEvent) { event.preventDefault(); create.mutate(); }
  if (review) return <div className="form-stack"><div className="notice"><strong>Possible duplicate — saved for review</strong><p>No contact has been created or merged. A manager must review the matching identifiers.</p><small>Review ID: {review.id}</small></div><button className="button primary" onClick={onClose}>Done</button></div>;
  return <form className="form-stack" onSubmit={submit}><Field title="Full name"><input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></Field><div className="form-row"><Field title="Phone" hint="Include a country code for numbers outside India."><input type="tel" required={!email.trim()} value={phone} onChange={e => setPhone(e.target.value)} /></Field><Field title="Email"><input type="email" required={!phone.trim()} value={email} onChange={e => setEmail(e.target.value)} /></Field></div><Field title="Branch"><select required value={branch} onChange={e => setBranch(e.target.value)}><option value="">Choose branch</option>{branches.data?.results.filter(b => b.is_active).map(b => <option value={b.id} key={b.id}>{b.name}</option>)}</select></Field>{branches.error && <FormError error={branches.error} />}<Field title="Enquiry source"><select value={source} onChange={e => setSource(e.target.value)}>{['manual', 'website', 'call', 'whatsapp'].map(s => <option key={s} value={s}>{s}</option>)}</select></Field><FormError error={create.error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={create.isPending || !branch}>{create.isPending ? 'Saving…' : 'Create contact'}</button></div></form>;
}
