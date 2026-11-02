'use client';
import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowUpRight, Clock3, Inbox, Pause, Play, RefreshCw, Search, UserRound } from 'lucide-react';
import { api, queryPath } from '@/lib/api';
import { date, label } from '@/lib/format';
import { useList } from '@/components/data';
import { Badge, Empty, ErrorState, FormError, Loading, PageHeader, Pagination } from '@/components/ui';
import type { Branch } from '@/lib/types';

type Entry = { key: string; source: string; source_label: string; name: string; phone: string | null; title: string;
  preview: string | null; branch: string; branch_name: string; status: string; owner_name: string | null;
  lead: string | null; lead_label: string | null; contact: string | null; received_at: string | null; activity_at: string;
  target: string; target_id: string };
type Feed = { count: number; page: number; page_size: number; has_next: boolean; server_time: string; sources: string[];
  totals: { all: number; needs_enquiry: number; unassigned: number; review: number; awaiting_reply: number; new: number };
  source_totals: Record<string, number>; whatsapp_mode: string; results: Entry[] };
const sourceNames: Record<string, string> = { website: 'Website forms', call: 'Calls', whatsapp: 'WhatsApp', manual: 'Manual / walk-in' };
const stateNames: Record<string, string> = { needs_enquiry: 'Needs enquiry', awaiting_reply: 'Awaiting reply', replied: 'Team replied',
  review: 'Identity review', transferred: 'Transferred out of scope', unassigned: 'Unassigned', rejected: 'Rejected' };
function destination(row: Entry) {
  if (row.lead) return `/leads/${row.lead}`;
  if (row.target === 'website') return `/enquiries?submission=${encodeURIComponent(row.target_id)}`;
  if (row.target === 'whatsapp') return `/inbox?conversation=${encodeURIComponent(row.target_id)}`;
  return `/calls?search=${encodeURIComponent(row.target_id)}`;
}

export default function LiveEnquiriesPage() {
  const [live, setLive] = useState(true); const [page, setPage] = useState(1); const [period, setPeriod] = useState('today');
  const [source, setSource] = useState(''); const [branch, setBranch] = useState(''); const [status, setStatus] = useState('');
  const [input, setInput] = useState(''); const [search, setSearch] = useState('');
  const branches = useList<Branch>('/branches/');
  const url = queryPath('/enquiry-dashboard/', { period, page, source, branch, status, search });
  const feed = useQuery({ queryKey: ['live-enquiries', url], queryFn: ({ signal }) => api<Feed>(url, { signal }),
    refetchInterval: live ? 5000 : false, refetchIntervalInBackground: true, refetchOnWindowFocus: true, retry: false });
  function filter(setter: (value: string) => void, value: string) { setter(value); setPage(1); }
  function submit(e: FormEvent) { e.preventDefault(); filter(setSearch, input.trim()); }
  const data = feed.data;
  const freshness = feed.isError ? 'Updates failed' : feed.fetchStatus === 'paused' ? 'Waiting for connection' : !live ? 'Monitoring paused' : feed.isFetching ? 'Checking for enquiries…' : 'Live monitoring';
  return <><PageHeader eyebrow="ONE VIEW FOR EVERY NEW OPPORTUNITY" title="Live enquiries dashboard" description="Monitor website forms, incoming calls, WhatsApp conversations and manual enquiries together.">
    <button className="button secondary" onClick={() => setLive(!live)}>{live ? <Pause size={16} /> : <Play size={16} />}{live ? 'Pause live updates' : 'Resume live updates'}</button>
    <button className="button primary" disabled={feed.isFetching} onClick={() => void feed.refetch()}><RefreshCw size={16} /> Refresh now</button>
  </PageHeader>
    <div className="live-feed-status"><span className={feed.isError || !live || feed.fetchStatus === 'paused' ? 'feed-indicator paused' : 'feed-indicator'} /><strong>{freshness}</strong><span>Checks every 5 seconds</span>{data && <time dateTime={data.server_time}>Last successful update: {new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Kolkata' }).format(new Date(data.server_time))} IST</time>}</div>
    <div className="notice call-integration-notice">Shows records received by this CRM. MyOperator live import and public website connections remain pending. WhatsApp mode: {data?.whatsapp_mode || 'checking…'}. Simulated replies do not clear real customer reply alerts.</div>
    {feed.error && <><ErrorState error={feed.error} retry={() => void feed.refetch()} />{data && <p className="form-error">Showing the last successful data below. Live updates are not current.</p>}</>}
    {feed.isPending ? <Loading text="Opening the live enquiry monitor…" /> : data && <>
      <div className="stats-grid">{[
        { name: 'All arrivals', count: data.totals.all, hint: 'Selected period and source', Icon: Inbox },
        { name: 'Unassigned enquiries', count: data.totals.unassigned, hint: 'Created leads waiting for an owner', Icon: UserRound },
        { name: 'Identity reviews', count: data.totals.review, hint: 'Manager confirmation needed', Icon: Activity },
        { name: 'WhatsApp replies due', count: data.totals.awaiting_reply, hint: data.sources.includes('whatsapp') ? 'Inbound conversations awaiting reply' : 'Messaging access is restricted', Icon: Clock3 },
      ].map(metric => <section className="stat-card" key={metric.name}><div className="stat-top"><span>{metric.name}</span><metric.Icon size={18} /></div><strong>{metric.name === 'WhatsApp replies due' && !data.sources.includes('whatsapp') ? '—' : metric.count}</strong><small>{metric.hint}</small></section>)}</div>
      <div className="feed-source-tabs"><button className={!source ? 'selected' : ''} onClick={() => filter(setSource, '')}>All sources</button>{data.sources.map(s => <button key={s} className={source === s ? 'selected' : ''} onClick={() => filter(setSource, s)}>{sourceNames[s] || label(s)} <span>{data.source_totals[s] || 0}</span></button>)}</div>
      <section className="panel"><div className="panel-toolbar"><form className="search-box" onSubmit={submit}><Search size={17} /><input aria-label="Search live enquiries" maxLength={200} placeholder="Name, phone, email or course…" value={input} onChange={e => setInput(e.target.value)} /><button className="button secondary small">Search</button></form>
        <div className="filter-group"><select aria-label="Enquiry branch" value={branch} onChange={e => filter(setBranch, e.target.value)}><option value="">All authorized branches</option>{branches.data?.results.map(b => <option value={b.id} key={b.id}>{b.name}</option>)}</select>
          <select aria-label="Enquiry period" value={period} onChange={e => filter(setPeriod, e.target.value)}><option value="today">Today (IST)</option><option value="24h">Last 24 hours</option><option value="all">All time</option></select>
          <select aria-label="Enquiry state" value={status} onChange={e => filter(setStatus, e.target.value)}><option value="">All states</option>{['new', 'unassigned', 'needs_enquiry', 'review', ...(data.sources.includes('whatsapp') ? ['awaiting_reply', 'replied'] : []), 'contacted', 'qualified', 'won', 'lost', 'rejected', 'transferred'].map(s => <option value={s} key={s}>{stateNames[s] || label(s)}</option>)}</select></div></div>
        <FormError error={branches.error} />
        {data.results.length ? <div className="table-wrap"><table className="live-enquiry-table"><thead><tr><th>Received</th><th>Contact / caller</th><th>Source & enquiry</th><th>Branch / assignment</th><th>Status</th><th>Action</th></tr></thead><tbody>{data.results.map(row => {
          const age = new Date(data.server_time).getTime() - new Date(row.activity_at).getTime(); const recent = age >= 0 && age < 120_000;
          return <tr key={row.key} className={recent ? 'recent-arrival' : ''}><td><span>{date(row.activity_at)}</span>{recent && <small className="feed-new-label">Just received</small>}{row.source === 'call' && row.received_at && <small className="cell-line muted">Call: {date(row.received_at)}</small>}</td>
            <td>{row.contact ? <Link className="text-link" href={`/contacts/${row.contact}`}>{row.name}</Link> : <strong>{row.name}</strong>}<small className="cell-line muted">{row.phone || 'No phone recorded'}</small></td>
            <td><Badge value={row.source}>{sourceNames[row.source] || label(row.source)}</Badge><strong className="cell-line">{row.title}</strong><small className="cell-line muted">{row.source_label}</small>{row.preview && <p className="feed-preview">{row.preview}</p>}</td>
            <td>{row.branch_name}<small className="cell-line muted">{row.owner_name || (row.status === 'review' ? 'Manager review' : row.status === 'awaiting_reply' ? 'Reply needed' : row.lead ? 'Unassigned' : 'Not yet assigned')}</small></td>
            <td><Badge value={row.status}>{stateNames[row.status] || label(row.status)}</Badge></td>
            <td><Link className="button secondary small" href={destination(row)}>{row.lead ? 'Open enquiry' : row.target === 'whatsapp' ? 'Open chat' : row.target === 'website' ? 'Open submission' : 'Open call'}<ArrowUpRight size={14} /></Link></td></tr>;
        })}</tbody></table></div> : <Empty title="No enquiries in this view">New records will appear automatically. Adjust the source, period or status filters to see earlier arrivals.</Empty>}
        <Pagination page={page} count={data.count} next={data.has_next} previous={page > 1} onPage={setPage} />
        <div className="panel-foot"><span>{data.totals.needs_enquiry} arrivals still need an enquiry</span><span>One row per source record or WhatsApp conversation · linked leads are not counted twice</span></div>
      </section>
    </>}
  </>;
}
