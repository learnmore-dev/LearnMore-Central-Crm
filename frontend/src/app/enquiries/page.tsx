'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryPath } from '@/lib/api';
import { date } from '@/lib/format';
import type { Page } from '@/lib/types';
import { useUser } from '@/components/providers';
import { Badge, Empty, ErrorState, Field, FormError, Loading, Modal, PageHeader, Pagination } from '@/components/ui';

type Enquiry = {
  id: string; website: string; full_name: string; phone: string; email: string; course: string; message: string;
  page_url: string; form_name: string; preferred_branch: string; training_mode: string; branch_name: string;
  status: string; lead: string | null; lead_label: string | null; owner_name: string | null; created_at: string;
  candidates: { id: string; full_name: string; contact_id: string }[];
};

function ReviewForm({ enquiry, onClose }: { enquiry: Enquiry; onClose: () => void }) {
  const client = useQueryClient(); const [decision, setDecision] = useState('linked'); const [contact, setContact] = useState(''); const [reason, setReason] = useState('');
  const resolve = useMutation({ mutationFn: () => api(`/website-enquiries/${enquiry.id}/resolve/`, { method: 'POST', body: { decision, reason, ...(decision === 'linked' ? { contact } : {}) } }),
    onSuccess: () => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); resolve.mutate(); }}>
    <div className="notice">An identifier matches an existing contact. Verify the student’s identity before creating this enquiry.</div>
    <Field title="Identity decision"><select value={decision} onChange={e => setDecision(e.target.value)}><option value="linked">Existing student — create a new enquiry</option><option value="separate">Different person sharing an identifier</option><option value="rejected">Reject this submission</option></select></Field>
    {decision === 'linked' && <Field title="Existing contact"><select required value={contact} onChange={e => setContact(e.target.value)}><option value="">Choose a verified contact</option>{enquiry.candidates.map(c => <option key={c.id} value={c.id}>{c.full_name} · {c.contact_id}</option>)}</select></Field>}
    {decision === 'linked' && !enquiry.candidates.length && <p className="muted">Matches outside your scope require global management review.</p>}
    <Field title="Review reason"><textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></Field>
    <FormError error={resolve.error} /><button className="button primary" disabled={resolve.isPending || !reason.trim() || (decision === 'linked' && !contact)}>{resolve.isPending ? 'Saving…' : 'Confirm identity decision'}</button>
  </form>;
}

export default function EnquiriesPage() {
  const submission = useSearchParams().get('submission') || '';
  const user = useUser(); const [page, setPage] = useState(1); const [status, setStatus] = useState(''); const [detail, setDetail] = useState<Enquiry | null>(null); const [review, setReview] = useState<Enquiry | null>(null);
  const url = queryPath('/website-enquiries/', { page, status, submission });
  const result = useQuery({ queryKey: ['list', url], queryFn: ({ signal }) => api<Page<Enquiry>>(url, { signal }), refetchInterval: 15_000 });
  return <><PageHeader eyebrow="FROM YOUR WEBSITES TO YOUR TEAM" title="Website enquiries" description="Form submissions from learnmoretech.in and learnmoretechnologies.in, with course details and counsellor assignment."><Link className="button secondary" href="/leads">Open lead pipeline</Link></PageHeader>
    <section className="panel"><div className="panel-toolbar"><Field title="Enquiry status"><select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">All submissions</option><option value="created">Enquiry created</option><option value="review">Identity review required</option><option value="rejected">Rejected after review</option></select></Field><span className="muted small-text">New enquiries also appear in the lead pipeline. Refreshes every 15 seconds.</span></div>
      {result.isPending ? <Loading text="Loading website enquiries…" /> : result.error ? <ErrorState error={result.error} retry={() => void result.refetch()} /> : result.data && <>
        {result.data.results.length ? <div className="table-wrap"><table><thead><tr><th>Student</th><th>Course & website</th><th>Branch & counsellor</th><th>Status</th><th>Received</th><th>Open</th></tr></thead><tbody>{result.data.results.map(row => <tr key={row.id}>
          <td><strong>{row.full_name}</strong><small className="cell-line">{row.phone || row.email}</small></td>
          <td>{row.course || 'General enquiry'}<small className="cell-line muted">{row.website} · {row.form_name || 'Enquiry form'}</small></td>
          <td>{row.branch_name}<small className="cell-line muted">{row.owner_name || (row.status === 'review' ? 'Awaiting identity review' : 'Unassigned queue')}</small></td>
          <td><Badge value={row.status}>{row.status === 'review' ? 'Identity review' : row.status === 'created' ? 'Enquiry created' : 'Rejected'}</Badge></td>
          <td className="muted">{date(row.created_at)}</td><td><div className="filter-group"><button className="button secondary small" onClick={() => setDetail(row)}>View submission</button>{row.lead && <Link className="text-link" href={`/leads/${row.lead}`}>{row.lead_label}</Link>}{row.status === 'review' && user.capabilities.manage_routing && <button className="button primary small" onClick={() => setReview(row)}>Review identity</button>}</div></td>
        </tr>)}</tbody></table></div> : <Empty title="No website enquiries yet">Once a website’s form handler is connected, submissions will appear here automatically.</Empty>}
        <Pagination count={result.data.count} page={page} next={!!result.data.next} previous={!!result.data.previous} onPage={setPage} />
      </>}
    </section>
    {detail && <Modal title={`Website enquiry · ${detail.full_name}`} onClose={() => setDetail(null)}><div className="form-stack"><p><strong>{detail.course || 'General enquiry'}</strong></p><p>{detail.phone} {detail.email}</p><p style={{ whiteSpace: 'pre-wrap' }}>{detail.message || 'No additional message.'}</p><p>Preferred branch: {detail.preferred_branch || detail.branch_name}</p><p>Training mode: {detail.training_mode || 'Not specified'}</p>{detail.page_url && <a className="text-link" href={detail.page_url} target="_blank" rel="noreferrer">View source page</a>}</div></Modal>}
    {review && <Modal title={`Review website enquiry · ${review.full_name}`} onClose={() => setReview(null)}><ReviewForm enquiry={review} onClose={() => setReview(null)} /></Modal>}
  </>;
}
