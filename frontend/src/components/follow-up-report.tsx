'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownToLine, ArrowUpRight, Clock3, RefreshCw } from 'lucide-react';
import { api, ApiError, queryPath } from '@/lib/api';
import { date, label } from '@/lib/format';
import type { Branch } from '@/lib/types';
import { useList } from './data';
import { useUser } from './providers';
import { Badge, Empty, ErrorState, FormError, Loading, PageHeader, Pagination } from './ui';

type Totals = { assigned: number; due: number; pending: number; overdue: number; completed_on_time: number; completed_late: number; missed_deadline: number; no_contact: number; unanswered: number };
type Counsellor = Totals & { owner: string; name: string };
type Row = { origin: string; task: string; lead: string | null; name: string; course: string; title: string; owner: string; category: string; due_at: string; delay_minutes: number; target: string; status: string; completed_at: string | null; resolution: string };
type Report = { server_time: string; totals: Totals; counsellors: Counsellor[]; results: Row[]; count: number; has_next: boolean };
const categories = [['overdue', 'Overdue work'], ['pending', 'Upcoming / pending'], ['no_contact', 'No contact recorded'], ['unanswered', 'Unanswered call recorded'], ['completed_on_time', 'Completed on time'], ['completed_late', 'Completed late'], ['missed_deadline', 'Missed deadline history'], ['all', 'All evidence']] as const;
function localDay(offset = 0) { const day = new Date(Date.now() + offset * 86400000); return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(day); }
function delay(minutes: number) { return minutes >= 1440 ? `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h` : minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`; }

export function FollowUpReport({ team = false, embedded = false }: { team?: boolean; embedded?: boolean }) {
  const user = useUser(); const allowed = !team || user.capabilities.global_scope || user.role === 'branch_manager';
  const [start, setStart] = useState(localDay(-29)); const [end, setEnd] = useState(localDay());
  const [branch, setBranch] = useState(''); const [owner, setOwner] = useState(''); const [category, setCategory] = useState('overdue'); const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false); const [exportError, setExportError] = useState<Error | null>(null);
  const branches = useList<Branch>('/branches/');
  const params = { team: team ? 'true' : 'false', start, end, branch, owner, category, page };
  const path = queryPath('/follow-up-report/', params);
  const result = useQuery({ queryKey: ['follow-up-report', path], queryFn: ({ signal }) => api<Report>(path, { signal }), enabled: allowed, refetchInterval: 30_000 });
  // Owner choices must stay available after selecting one counsellor.
  const rosterPath = queryPath('/follow-up-report/', { team: 'true', start, end, branch });
  const roster = useQuery({ queryKey: ['follow-up-report-roster', rosterPath], queryFn: ({ signal }) => api<Report>(rosterPath, { signal }), enabled: allowed && team, staleTime: 30_000 });
  const change = (setter: (value: string) => void, value: string) => { setter(value); setPage(1); };
  async function download() {
    setExporting(true); setExportError(null);
    try {
      const response = await fetch('/api/v1' + queryPath('/follow-up-report/', { ...params, export: 'csv' }), { credentials: 'include', cache: 'no-store' });
      if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => null));
      const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'learnmore-follow-up-report.csv'; document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setExportError(error instanceof Error ? error : new Error('Export failed.')); }
    finally { setExporting(false); }
  }
  if (!allowed) return <Empty title="Manager access required">Counsellors can see their personal report in My work today.</Empty>;
  return <div className="followup-report">
    {embedded ? <div className="section-heading"><div><span className="eyebrow">YOUR FOLLOW-UP RECORD</span><h2>Reminders & accountability</h2></div></div> : <PageHeader eyebrow="LEARNMORE TEAM PERFORMANCE" title="Counsellor follow-up report" description="See outstanding work, recorded contact attempts and deadline history for each counsellor."><Link className="button secondary" href="/my-work">My work today</Link></PageHeader>}
    <section className="panel"><div className="report-filters"><label className="field"><span>From (IST)</span><input type="date" aria-label="Report start date" value={start} onChange={e => change(setStart, e.target.value)} /></label><label className="field"><span>To (IST)</span><input type="date" aria-label="Report end date" value={end} onChange={e => change(setEnd, e.target.value)} /></label>{team && <><label className="field"><span>Branch</span><select aria-label="Report branch" value={branch} onChange={e => { change(setBranch, e.target.value); setOwner(''); }}><option value="">All authorized branches</option>{branches.data?.results.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label><label className="field"><span>Counsellor</span><select aria-label="Report counsellor" value={owner} onChange={e => change(setOwner, e.target.value)}><option value="">All counsellors & unassigned</option>{roster.data?.counsellors.filter(c => c.owner).map(c => <option key={c.owner} value={c.owner}>{c.name}</option>)}</select></label></>}<button className="button secondary" disabled={result.isFetching} onClick={() => { void result.refetch(); if (team) void roster.refetch(); }}><RefreshCw size={15} /> Refresh</button><button className="button primary" onClick={() => void download()} disabled={exporting || !result.data || !!result.error}><ArrowDownToLine size={15} />{exporting ? 'Exporting…' : 'Export CSV'}</button></div><div className="report-explanation">Task metrics use <strong>deadline dates</strong>; contact gaps use <strong>enquiry first-received dates</strong>. Active assigned enquiries are current totals. A missing record does not prove a call was never made. Maximum date range: 93 days.</div><FormError error={exportError} />{team && (branches.error || roster.error) && <FormError error={branches.error || roster.error} />}</section>
    {result.isPending ? <Loading /> : result.error ? <ErrorState error={result.error} retry={() => void result.refetch()} /> : result.data && <>
      <div className="reminder-metrics">{[
        ['overdue', 'Overdue tasks', result.data.totals.overdue, 'rose'], ['no_contact', 'No contact recorded', result.data.totals.no_contact, 'amber'], ['unanswered', 'Unanswered calls', result.data.totals.unanswered, 'purple'], ['missed_deadline', 'Missed deadlines', result.data.totals.missed_deadline, 'mint'],
      ].map(([key, title, value, tone]) => <button key={String(key)} className={`reminder-metric ${category === key ? 'selected' : ''}`} onClick={() => change(setCategory, String(key))}><span className={`metric-icon ${tone}`}><Clock3 size={18} /></span><strong>{value}</strong><span>{title}</span><small>View records <ArrowUpRight size={12} /></small></button>)}</div>
      {team && <section className="panel"><div className="panel-head"><div><h2>Counsellor scorecard</h2><p>Task counts include callbacks, assignment reminders and demo work. Deadline history remains after completion or reassignment.</p></div></div><div className="table-wrap"><table><thead><tr><th>Counsellor</th><th>Active assigned</th><th>Tasks due</th><th>Pending</th><th>Overdue</th><th>On time</th><th>Late</th><th>Missed deadlines</th><th>No contact recorded</th><th>Unanswered calls</th></tr></thead><tbody>{result.data.counsellors.map(c => <tr key={c.owner || 'unassigned'}><td><strong>{c.name}</strong></td><td>{c.assigned}</td><td>{c.due}</td><td>{c.pending}</td><td><button className="report-count overdue-text" onClick={() => { setOwner(c.owner); change(setCategory, 'overdue'); }}>{c.overdue}</button></td><td>{c.completed_on_time}</td><td>{c.completed_late}</td><td><button className="report-count" onClick={() => { setOwner(c.owner); change(setCategory, 'missed_deadline'); }}>{c.missed_deadline}</button></td><td>{c.no_contact}</td><td>{c.unanswered}</td></tr>)}</tbody></table></div></section>}
      <section className="panel"><div className="panel-toolbar"><div><h2>{categories.find(([key]) => key === category)?.[1]}</h2><span className="small-text muted">Updated {date(result.data.server_time)}</span></div><select aria-label="Report category" value={category} onChange={e => change(setCategory, e.target.value)}>{categories.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></div>
        <div className="report-explanation">{category === 'missed_deadline' ? 'One record per task’s first missed deadline, attributed to the responsible counsellor when recorded. Earlier cancelled work without a recorded breach cannot be reconstructed.' : category === 'unanswered' ? 'A new enquiry has an unanswered outgoing call recorded, with no answered call or accepted live staff message since the enquiry was first received. This is a student response outcome, not a counsellor failure.' : category === 'no_contact' ? 'New enquiries without a recorded outgoing call, answered call or accepted live staff message since first receipt. Internal notes and assignment acknowledgement do not establish student contact.' : category === 'all' ? 'All evidence includes task records and separate historical deadline records; the same task can appear in both categories.' : 'Open an enquiry or its workspace to record the outcome, complete work or agree the next step.'}</div>
        {result.data.results.length ? <div className="table-wrap"><table><thead><tr><th>Student / course</th>{team && <th>Counsellor</th>}<th>Required action</th><th>Deadline / enquiry received</th><th>Delay / age</th><th>Result</th><th>Action</th></tr></thead><tbody>{result.data.results.map((r, i) => <tr key={`${r.origin}:${r.task}:${r.category}:${i}`}><td><strong>{r.name}</strong><small className="cell-line muted">{r.course}</small></td>{team && <td>{r.owner}</td>}<td className="report-wrap"><strong>{r.title}</strong><small className="cell-line muted">{label(r.origin)}</small>{r.resolution && <p className="feed-preview">{r.resolution}</p>}</td><td>{date(r.due_at)}{r.completed_at && <small className="cell-line muted">Completed {date(r.completed_at)}</small>}</td><td>{delay(r.delay_minutes)}</td><td><Badge value={r.category} /></td><td>{r.target ? <Link href={r.target} className="button secondary small">Open <ArrowUpRight size={14} /></Link> : <span className="muted small-text">Transferred out of scope</span>}</td></tr>)}</tbody></table></div> : <Empty title="No records match this view">Choose another category or date range.</Empty>}
        <Pagination count={result.data.count} page={page} previous={page > 1} next={result.data.has_next} onPage={setPage} />
      </section>
    </>}
  </div>;
}
