'use client';
import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api, ApiError } from '@/lib/api';
import type { Branch, Lead, Review } from '@/lib/types';
import { useList } from './data';
import { useUser } from './providers';
import { Field, FormError } from './ui';
import { NextActionField } from './next-action-field';
import { LearningPreferenceFields, learningPreferences } from './learning-preferences';
import { EnquiryContactDetails } from './enquiry-contact-details';

export function LeadForm({ contact, onClose }: { contact?: string; onClose: () => void }) {
  const user = useUser(); const client = useQueryClient(); const router = useRouter(); const branches = useList<Branch>('/branches/');
  const [preferences, setPreferences] = useState(() => learningPreferences(null));
  const [name, setName] = useState(''); const [mobile, setMobile] = useState(''); const [email, setEmail] = useState('');
  const [branch, setBranch] = useState(user.branch || ''); const [source, setSource] = useState('manual');
  const [action, setAction] = useState(''); const [deadline, setDeadline] = useState(''); const [review, setReview] = useState<Review | null>(null);
  const create = useMutation({ mutationFn: () => api<Lead>(contact ? '/leads/' : '/leads/intake/', { method: 'POST', body: {
    ...(contact ? { contact } : { candidate: { full_name: name, mobile, email } }),
    title: preferences.course_interest, branch, source, qualification: preferences,
    ...(action.trim() ? { next_action: action, next_action_at: new Date(deadline).toISOString() } : {}),
  } }), onSuccess: lead => { void client.invalidateQueries({ predicate: query => query.queryKey[0] !== 'session' }); onClose(); router.push(`/leads/${lead.id}`); },
    onError: error => { if (error instanceof ApiError && error.status === 409) setReview(error.data as Review); } });
  function submit(event: FormEvent) { event.preventDefault(); create.mutate(); }
  if (review) return <div className="form-stack"><div className="notice"><strong>Possible duplicate — saved for review</strong><p>No new contact or enquiry was created. A manager must review the matching identifiers before you continue.</p><small>Review ID: {review.id}</small></div><div className="form-actions"><button className="button secondary" onClick={() => setReview(null)}>Review entered details</button><button className="button primary" onClick={onClose}>Done</button></div></div>;
  return <form onSubmit={submit} className="form-stack unified-enquiry-form">
    {contact ? <EnquiryContactDetails id={contact} /> : <fieldset className="enquiry-form-section"><legend>Candidate details</legend><Field title="Candidate name"><input required maxLength={200} value={name} onChange={event => setName(event.target.value)} /></Field><div className="form-row"><Field title="Mobile"><input type="tel" required={!email.trim()} maxLength={40} value={mobile} onChange={event => setMobile(event.target.value)} /></Field><Field title="Email"><input type="email" required={!mobile.trim()} value={email} onChange={event => setEmail(event.target.value)} /></Field></div></fieldset>}
    <fieldset className="enquiry-form-section"><legend>Course & training preferences</legend><LearningPreferenceFields value={preferences} onChange={setPreferences} /></fieldset>
    <fieldset className="enquiry-form-section"><legend>Assignment & follow-up</legend><div className="form-row"><Field title="Assigned branch"><select required value={branch} onChange={event => setBranch(event.target.value)}><option value="">Choose branch</option>{branches.data?.results.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field title="Enquiry source"><select value={source} onChange={event => setSource(event.target.value)}><option value="manual">Walk-in / manual</option><option value="website">Website</option><option value="call">Call</option><option value="whatsapp">WhatsApp</option></select></Field></div><p className="muted small-text">The assigned branch uses the existing counsellor routing rules. Preferred training branch is recorded separately.</p><NextActionField title="Next action (optional)" hint="Leave blank to use the branch’s new-enquiry deadline." value={action} onChange={setAction} />{action.trim() && <Field title="Deadline (your local time)"><input type="datetime-local" required value={deadline} onChange={event => setDeadline(event.target.value)} /></Field>}</fieldset>
    <FormError error={branches.error || create.error} /><div className="form-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={create.isPending || !branch}>{create.isPending ? 'Creating…' : 'Create enquiry'}</button></div>
  </form>;
}
