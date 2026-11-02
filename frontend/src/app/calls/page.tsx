'use client';
import { CourseField } from '@/components/course-field';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { PhoneIncoming, PhoneOutgoing, Plus, Search } from 'lucide-react';
import { useList } from '@/components/data';
import { useUser } from '@/components/providers';
import { Badge, Empty, ErrorState, Field, FormError, Loading, Modal, PageHeader, Pagination } from '@/components/ui';
import { api, queryPath } from '@/lib/api';
import { date, localInputDate } from '@/lib/format';
import type { Branch, Page } from '@/lib/types';

type Call = { id: string; caller_phone: string; caller_name: string; business_phone: string; branch_name: string;
  direction: string; status: string; started_at: string; duration_seconds: number; forwarded_to: string; notes: string;
  contact: string | null; contact_name: string | null; contact_label: string | null; identity_status: string;
  lead: string | null; lead_label: string | null; candidates: { id: string; full_name: string; contact_id: string }[] };

function CallForm({ onClose }: { onClose: () => void }) {
  const user = useUser(); const client = useQueryClient(); const branches = useList<Branch>('/branches/');
  const [branch, setBranch] = useState(user.branch || ''); const [phone, setPhone] = useState(''); const [name, setName] = useState('');
  const [business, setBusiness] = useState(''); const [direction, setDirection] = useState('incoming'); const [status, setStatus] = useState('answered');
  const [started, setStarted] = useState(localInputDate(new Date().toISOString())); const [duration, setDuration] = useState(0);
  const [forwarded, setForwarded] = useState(''); const [notes, setNotes] = useState('');
  const requestKey = useRef<{ body: string; key: string } | null>(null);
  const save = useMutation({ mutationFn: () => {
    const body = { branch, caller_phone: phone, caller_name: name, business_phone: business, direction, status,
      started_at: new Date(started).toISOString(), duration_seconds: duration, forwarded_to: forwarded, notes };
    const serialized = JSON.stringify(body);
    if (requestKey.current?.body !== serialized) requestKey.current = { body: serialized, key: crypto.randomUUID() };
    return api('/call-logs/', { method: 'POST', body: { ...body, client_key: requestKey.current.key } });
  }, onSuccess: () => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
    <div className="notice">This saves a manual call record. The phone number will be matched to a contact automatically.</div>
    <div className="form-row"><Field title="Caller number"><input required type="tel" value={phone} onChange={e => setPhone(e.target.value)} maxLength={40} /></Field><Field title="Caller name (optional)"><input maxLength={200} value={name} onChange={e => setName(e.target.value)} /></Field></div>
    <Field title="Branch"><select required value={branch} onChange={e => setBranch(e.target.value)}><option value="">Choose branch</option>{branches.data?.results.filter(b => b.is_active).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>
    <Field title="Business number (optional)"><input type="tel" value={business} onChange={e => setBusiness(e.target.value)} maxLength={40} /></Field>
    <div className="form-row"><Field title="Direction"><select value={direction} onChange={e => setDirection(e.target.value)}><option value="incoming">Incoming</option><option value="outgoing">Outgoing</option></select></Field><Field title="Call status"><select value={status} onChange={e => setStatus(e.target.value)}><option value="answered">Answered</option><option value="missed">Missed</option><option value="voicemail">Voicemail</option></select></Field></div>
    <div className="form-row"><Field title="Call time (your local time)"><input required type="datetime-local" value={started} onChange={e => setStarted(e.target.value)} /></Field><Field title="Duration in seconds"><input required type="number" min={0} max={604800} value={duration} onChange={e => setDuration(Number(e.target.value))} /></Field></div>
    <Field title="Received by / forwarded to"><input maxLength={200} value={forwarded} onChange={e => setForwarded(e.target.value)} placeholder="e.g. Manager 1 · Admissions" /></Field>
    <Field title="Call notes"><textarea maxLength={2000} value={notes} onChange={e => setNotes(e.target.value)} /></Field>
    <FormError error={branches.error || save.error} /><button className="button primary" disabled={!branch || save.isPending}>{save.isPending ? 'Saving…' : 'Save call & match contact'}</button>
  </form>;
}

function EnquiryForm({ call, onClose }: { call: Call; onClose: () => void }) {
  const client = useQueryClient(); const [title, setTitle] = useState('Phone enquiry');
  const create = useMutation({ mutationFn: () => api(`/call-logs/${call.id}/create-enquiry/`, { method: 'POST', body: { title } }),
    onSuccess: () => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); create.mutate(); }}>
    <p><strong>{call.contact_name}</strong> · {call.caller_phone}</p>
    <CourseField title="Enquiry title / course" required value={title} onChange={setTitle} />
    <div className="notice">This enquiry will use {call.branch_name} and the branch’s counsellor routing. The call remains linked to the contact and enquiry.</div>
    <FormError error={create.error} /><button className="button primary" disabled={!title.trim() || create.isPending}>{create.isPending ? 'Creating…' : 'Create enquiry'}</button>
  </form>;
}

function ReviewForm({ call, onClose }: { call: Call; onClose: () => void }) {
  const client = useQueryClient(); const [decision, setDecision] = useState('linked'); const [contact, setContact] = useState(''); const [reason, setReason] = useState('');
  const save = useMutation({ mutationFn: () => api(`/call-logs/${call.id}/resolve-contact/`, { method: 'POST', body: { decision, reason, ...(decision === 'linked' ? { contact } : {}) } }),
    onSuccess: () => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
    <p>{call.caller_phone} matches an existing identity. Confirm who called before linking this call.</p>
    <Field title="Contact decision"><select value={decision} onChange={e => setDecision(e.target.value)}><option value="linked">Link verified existing contact</option><option value="separate">Different person sharing this number</option><option value="rejected">Reject identity link</option></select></Field>
    {decision === 'linked' && <Field title="Existing contact"><select required value={contact} onChange={e => setContact(e.target.value)}><option value="">Choose contact</option>{call.candidates.map(c => <option key={c.id} value={c.id}>{c.full_name} · {c.contact_id}</option>)}</select></Field>}
    {decision === 'linked' && !call.candidates.length && <p className="muted">A manager with global access must review contacts outside your branch.</p>}
    <Field title="Reason"><textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></Field>
    <FormError error={save.error} /><button className="button primary" disabled={save.isPending || !reason.trim() || (decision === 'linked' && !contact)}>Confirm contact</button>
  </form>;
}

export default function CallsPage() {
  const initialSearch = useSearchParams().get('search') || '';
  const user = useUser(); const [page, setPage] = useState(1); const [input, setInput] = useState(initialSearch); const [search, setSearch] = useState(initialSearch); const [status, setStatus] = useState(''); const [direction, setDirection] = useState('');
  const [adding, setAdding] = useState(false); const [enquiry, setEnquiry] = useState<Call | null>(null); const [review, setReview] = useState<Call | null>(null); const [detail, setDetail] = useState<Call | null>(null);
  const url = queryPath('/call-logs/', { page, search, status, direction });
  const calls = useQuery({ queryKey: ['list', url], queryFn: ({ signal }) => api<Page<Call>>(url, { signal }), refetchInterval: 15_000 });
  function submit(e: FormEvent) { e.preventDefault(); setSearch(input.trim()); setPage(1); }
  return <><PageHeader eyebrow="EVERY CALL, ONE CONNECTED HISTORY" title="Call logs" description="Track business calls, forwarded calls and missed opportunities, with the right contact and next step.">{user.capabilities.sales_write && <button className="button primary" onClick={() => setAdding(true)}><Plus size={16} /> Add call log</button>}</PageHeader>
    <div className="notice call-integration-notice"><strong>MyOperator API is not connected yet.</strong> Calls added here are manual records. Live call import will be connected later.</div>
    <section className="panel"><div className="panel-toolbar"><form className="search-box" onSubmit={submit}><Search size={17} /><input aria-label="Search calls" maxLength={200} placeholder="Phone, contact or team member…" value={input} onChange={e => setInput(e.target.value)} /><button className="button secondary small">Search</button></form><div className="filter-group"><select aria-label="Call direction" value={direction} onChange={e => { setDirection(e.target.value); setPage(1); }}><option value="">All calls</option><option value="incoming">Incoming</option><option value="outgoing">Outgoing</option></select><select aria-label="Call status" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">All statuses</option><option value="answered">Answered</option><option value="missed">Missed</option><option value="voicemail">Voicemail</option></select></div></div>
      {calls.isPending ? <Loading text="Loading call logs…" /> : calls.error ? <ErrorState error={calls.error} retry={() => void calls.refetch()} /> : calls.data && <>
        {calls.data.results.length ? <div className="table-wrap"><table className="call-table"><thead><tr><th>Who</th><th>What</th><th>When</th><th>Duration</th><th className="call-actions-heading">Actions</th></tr></thead><tbody>{calls.data.results.map(call => <tr key={call.id}>
          <td><div className="person-cell"><span className={`call-symbol ${call.status}`}>{call.direction === 'incoming' ? <PhoneIncoming size={19} /> : <PhoneOutgoing size={19} />}</span><span>{call.contact ? <Link className="text-link" href={`/contacts/${call.contact}`}>{call.contact_name}</Link> : <strong>{call.caller_name || call.caller_phone}</strong>}<small className="cell-line muted">{call.caller_phone}</small>{call.identity_status === 'review' && <small className="cell-line form-error">Contact review required</small>}</span></div></td>
          <td><Badge value={call.status} /><span className="cell-line">{call.direction === 'incoming' ? 'Incoming call' : 'Outgoing call'}{call.forwarded_to ? ` · ${call.status === 'missed' ? 'Missed by' : 'Received by / forwarded to'} ${call.forwarded_to}` : ''}</span><small className="cell-line muted">{call.branch_name} · Manually recorded{call.business_phone ? ` · ${call.business_phone}` : ''}</small></td>
          <td className="muted">{date(call.started_at)}</td><td>{Math.floor(call.duration_seconds / 60)}m {call.duration_seconds % 60}s</td>
          <td><div className="call-row-actions"><button className="button secondary small" onClick={() => setDetail(call)}>Details</button>{call.lead ? <Link className="button secondary small" href={`/leads/${call.lead}`}>View enquiry · {call.lead_label}</Link> : call.contact && user.capabilities.sales_write ? <button className="button primary small" onClick={() => setEnquiry(call)}><Plus size={14} /> Create enquiry</button> : call.identity_status === 'review' && user.capabilities.manage_routing ? <button className="button secondary small" onClick={() => setReview(call)}>Review contact</button> : !call.contact && <span className="muted small-text">{call.identity_status === 'rejected' ? 'Identity link rejected' : 'Awaiting contact review'}</span>}</div></td>
        </tr>)}</tbody></table></div> : <Empty title="No call logs yet">Add a call record to match its caller to a contact. MyOperator calls will appear after API integration.</Empty>}
        <Pagination page={page} count={calls.data.count} next={!!calls.data.next} previous={!!calls.data.previous} onPage={setPage} />
      </>}
    </section>
    {adding && <Modal title="Add call log" onClose={() => setAdding(false)}><CallForm onClose={() => setAdding(false)} /></Modal>}
    {enquiry && <Modal title="Create enquiry from call" onClose={() => setEnquiry(null)}><EnquiryForm call={enquiry} onClose={() => setEnquiry(null)} /></Modal>}
    {review && <Modal title="Review caller contact" onClose={() => setReview(null)}><ReviewForm call={review} onClose={() => setReview(null)} /></Modal>}
    {detail && <Modal title="Call details" onClose={() => setDetail(null)}><div className="form-stack"><p><strong>{detail.contact_name || detail.caller_name || detail.caller_phone}</strong></p><p>{date(detail.started_at)} · {detail.status} · {detail.direction}</p><p>Business number: {detail.business_phone || 'Not recorded'}</p><p>Forwarded to: {detail.forwarded_to || 'Not recorded'}</p><p style={{ whiteSpace: 'pre-wrap' }}>{detail.notes || 'No notes recorded.'}</p></div></Modal>}
  </>;
}
