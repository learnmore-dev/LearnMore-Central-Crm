'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { MessageSquare, Phone, History, ArrowUpRight } from 'lucide-react';
import { api, queryPath } from '@/lib/api';
import { date, label } from '@/lib/format';
import { Badge, Empty, ErrorState, Loading, Pagination } from './ui';

type HistoryData = { count: number; has_next: boolean; enquiries: { id: string; lead_id: string; title: string; status: string; branch: string; owner: string; received_at?: string; received_via?: string }[]; results: { id: string; source: string; title: string; body: string; actor: string; branch: string; occurred_at: string; status: string; mode: string; target: string }[] };
export function ContactHistory({ contactId }: { contactId: string }) {
  const [source, setSource] = useState('all'); const [page, setPage] = useState(1);
  const path = queryPath(`/contacts/${contactId}/history/`, { source, page });
  const result = useQuery({ queryKey: ['contact-history', path], queryFn: ({ signal }) => api<HistoryData>(path, { signal }), refetchInterval: 15_000 });
  return <section className="panel contact-history"><div className="panel-head"><div><span className="panel-kicker">ONE CONTACT. THE FULL CONTEXT.</span><h2>Communication & ownership history</h2><p>WhatsApp chats, logged calls and team notes in your authorized branches.</p></div><select aria-label="History source" value={source} onChange={e => { setSource(e.target.value); setPage(1); }}><option value="all">All history</option><option value="whatsapp">WhatsApp</option><option value="call">Calls</option><option value="activity">Notes & activity</option></select></div>
    {result.isPending ? <Loading /> : result.error ? <ErrorState error={result.error} retry={() => void result.refetch()} /> : result.data && <>
      <div className="history-ownership">{result.data.enquiries.map(enquiry => <Link href={`/leads/${enquiry.id}`} key={enquiry.id}><span><strong>{enquiry.title}</strong><small>{enquiry.lead_id} · {enquiry.branch}</small>{enquiry.received_at && <small>First received {date(enquiry.received_at)} IST{enquiry.received_via === 'crm_recorded' ? ' · CRM record' : ''}</small>}</span><span><strong>{enquiry.owner}</strong><Badge value={enquiry.status} /></span><ArrowUpRight size={16} /></Link>)}</div>
      {result.data.results.length ? <div className="communication-stream">{result.data.results.map(row => { const Icon = row.source === 'whatsapp' ? MessageSquare : row.source === 'call' ? Phone : History; return <article key={`${row.source}:${row.id}`} className="communication-item"><span className={`communication-icon ${row.source}`}><Icon size={18} /></span><div><div className="communication-meta"><strong>{label(row.title)}</strong><time dateTime={row.occurred_at}>{date(row.occurred_at)}</time></div><p>{row.body || 'No discussion notes recorded.'}</p><div className="communication-foot"><span>{row.actor} · {row.branch}{row.mode ? ` · ${row.mode}` : ''}</span>{row.status && <Badge value={row.status} />}{row.target && <Link className="text-link" href={row.target}>Open {row.source === 'whatsapp' ? 'chat' : 'call'} <ArrowUpRight size={13} /></Link>}</div></div></article>; })}</div> : <Empty title="No communication in this view">Logged calls, messages and internal notes will appear here. Call audio and automatic transcription are not collected.</Empty>}
      <Pagination count={result.data.count} page={page} next={result.data.has_next} previous={page > 1} onPage={setPage} />
    </>}
  </section>;
}
