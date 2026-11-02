'use client';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import { ArrowRight, ArrowUpRight, ContactRound, GitBranch, Inbox, Clock3, MapPin, Plus, Users, Sparkles, CheckCheck, MessageSquare, Zap } from 'lucide-react';
import { useRecord, useList } from './data';
import { useUser } from './providers';
import { Empty, ErrorState, Loading, PageHeader } from './ui';
import { Timeline } from './timeline';
import { queryPath } from '@/lib/api';
import { label } from '@/lib/format';
import type { Branch, Dashboard } from '@/lib/types';
import { statuses } from '@/lib/types';

export function Overview() {
  const user = useUser(); const router = useRouter(); const selected = useSearchParams().get('branch') || '';
  const branches = useList<Branch>('/branches/');
  const result = useRecord<Dashboard>(queryPath('/dashboard/', { branch: selected }));
  const data = result.data;
  const total = data ? Object.values(data.pipeline).reduce((a, b) => a + b, 0) : 0;
  return <div className="overview-page">
    <PageHeader eyebrow="YOUR WORKSPACE, AT A GLANCE" title={`Welcome back, ${user.first_name || user.username}.`} description="Make every conversation the start of something great.">
      <select aria-label="Dashboard branch" value={selected} onChange={e => router.push(e.target.value ? `/?branch=${e.target.value}` : '/')}><option value="">{user.capabilities.global_scope ? 'All branches' : 'Your branch'}</option>{branches.data?.results.map(branch => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select>
      {user.capabilities.sales_write && <Link className="button secondary" href="/my-work"><Clock3 size={16} /> My reminders</Link>}
      <Link className="button primary" href="/leads"><Plus size={17} /> View pipeline</Link>
    </PageHeader>
    {result.isPending ? <Loading text="Loading your overview…" /> : result.error ? <ErrorState error={result.error} retry={() => void result.refetch()} /> : data && <>
      <section className="workspace-hero">
        <div className="hero-copy"><span className="hero-kicker"><Sparkles size={14} /> CONNECTIONS THAT COUNT</span><h2>A little follow-up.<br />A bigger future.</h2><p>{data.unassigned ? `${data.unassigned} ${data.unassigned === 1 ? 'enquiry is' : 'enquiries are'} waiting for an owner. Help your next learner take the first step.` : 'Your assignment queue is clear. Keep the momentum going with your next conversation.'}</p><Link className="hero-cta" href={data.unassigned ? '/leads?queue=true' : '/tasks'}>{data.unassigned ? 'Review unassigned enquiries' : 'Explore follow-ups'}<ArrowUpRight size={17} /></Link></div>
        <div className="hero-focus"><span className="focus-label"><span className="focus-dot" /> CURRENT PRIORITIES</span><Link href="/tasks"><span className="focus-icon"><Clock3 size={19} /></span><span><strong>{data.overdue_tasks}</strong><small>Overdue follow-ups</small></span><ArrowUpRight size={17} /></Link><Link href="/leads?queue=true"><span className="focus-icon"><Inbox size={19} /></span><span><strong>{data.unassigned}</strong><small>Enquiries to assign</small></span><ArrowUpRight size={17} /></Link></div>
      </section>
      <div className="section-heading"><div><span className="eyebrow">THE BIG PICTURE</span><h2>Your CRM at a glance</h2></div><span className="scope-note">{branches.data?.results.find(b => b.id === selected)?.name || (user.capabilities.global_scope ? 'Across your branches' : 'Within your scope')}</span></div>
      <div className="stats-grid">{[
        { title: 'Total contacts', value: data.contacts, hint: 'People in your network', Icon: ContactRound, tone: 'mint', href: '/contacts' },
        { title: 'Active enquiries', value: data.active_leads, hint: 'Conversations moving forward', Icon: GitBranch, tone: 'purple', href: '/leads' },
        { title: 'Unassigned', value: data.unassigned, hint: 'Ready for a counsellor', Icon: Inbox, tone: 'amber', href: '/leads?queue=true' },
        { title: 'Overdue follow-ups', value: data.overdue_tasks, hint: 'Your next priority', Icon: Clock3, tone: 'rose', href: '/tasks' },
      ].map(({ title, value, hint, Icon, tone, href }) => <Link className={`stat-card metric-${tone}`} href={href} key={title}><div className="stat-top"><span>{title}</span><span className={`metric-icon ${tone}`}><Icon size={20} /></span></div><strong>{value.toLocaleString('en-IN')}</strong><div className="stat-bottom"><small>{hint}</small><ArrowUpRight size={15} /></div></Link>)}</div>
      <div className="dashboard-grid"><section className="panel"><div className="panel-head"><div><span className="panel-kicker">FROM INTEREST TO ENROLMENT</span><h2>Enquiry pipeline</h2><p>See where every opportunity stands.</p></div><Link className="panel-icon-link" aria-label="Open pipeline" href="/leads"><ArrowUpRight size={19} /></Link></div><div className="pipeline-total"><strong>{total.toLocaleString('en-IN')}</strong><span>Total enquiries<span className="pipeline-total-note">in your selected scope</span></span></div><div className="pipeline-chart">{statuses.map(status => { const count = data.pipeline[status]; const max = Math.max(...Object.values(data.pipeline), 1); return <div className="pipeline-bar" key={status}><span><i className={`status-dot ${status}`} />{label(status)}</span><div className="bar-track"><div className={`bar-fill ${status}`} style={{ width: `${count / max * 100}%` }} /></div><strong>{count}</strong></div>; })}</div><div className="panel-foot"><span><span className="availability-dot" /> {data.available_counsellors} available counsellors</span><Link className="text-link" href="/leads">View pipeline <ArrowRight size={14} /></Link></div></section>
      <section className="panel"><div className="panel-head"><div><span className="panel-kicker">ONE TEAM. MANY POSSIBILITIES.</span><h2>Branch pulse</h2><p>Your local teams, connected.</p></div><span className="count-pill">{data.branches.length} branches</span></div><div className="branch-summary">{data.branches.length ? data.branches.map(branch => <Link className="branch-summary-row" key={branch.id} href={`/?branch=${branch.id}`}><span className="location-icon"><MapPin size={20} /></span><div><strong>{branch.name}</strong><small><i className={`branch-state ${branch.is_active ? 'is-active' : ''}`} />{branch.is_active ? 'Active' : 'Inactive'} · {branch.unassigned} unassigned</small></div><span className="branch-lead-count"><strong>{branch.active_leads}</strong><small>active leads</small></span><ArrowUpRight className="branch-arrow" size={16} /></Link>) : <Empty title="No branches in scope" />}</div><div className="panel-foot"><span>Every branch. A shared ambition.</span><Link className="text-link" href="/branches">View branches <ArrowRight size={14} /></Link></div></section></div>
      <div className="dashboard-lower"><section className="panel activity-panel"><div className="panel-head"><div><span className="panel-kicker">THE LATEST CONNECTIONS</span><h2>Activity stream</h2><p>A shared view of your team’s progress.</p></div><Link className="text-link" href="/contacts">View contacts <ArrowUpRight size={16} /></Link></div><Timeline activities={data.recent_activities} compact /></section>
      <aside className="dashboard-shortcuts"><section className="panel"><div className="panel-head"><div><span className="panel-kicker">KEEP THINGS MOVING</span><h2>Your next move</h2></div><Zap size={19} className="muted" /></div><div className="shortcut-list"><Link href="/tasks"><span className="shortcut-icon mint"><CheckCheck size={19} /></span><span><strong>Follow-ups</strong><small>Give every enquiry a next step</small></span><ArrowRight size={16} /></Link><Link href="/live-enquiries"><span className="shortcut-icon purple"><MessageSquare size={19} /></span><span><strong>Live enquiries</strong><small>See the latest conversations</small></span><ArrowRight size={16} /></Link>{user.capabilities.sales_write && <Link href="/automation"><span className="shortcut-icon amber"><Zap size={19} /></span><span><strong>Automation & follow-up</strong><small>Build a consistent experience</small></span><ArrowRight size={16} /></Link>}</div></section><div className="team-note"><Users size={24} /><h3>Better, together.</h3><p>One connected workspace for every learner, every counsellor and every next step.</p></div></aside></div>
    </>}
  </div>;
}
