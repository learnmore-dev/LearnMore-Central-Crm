'use client';
import Link from 'next/link';
import { MessageSquare, GitBranch, UserRound, CheckCheck } from 'lucide-react';
import { date, label } from '@/lib/format';
import type { Activity } from '@/lib/types';
import { Empty } from './ui';
export function Timeline({ activities, compact = false }: { activities: Activity[]; compact?: boolean }) {
  if (!activities.length) return <Empty title="No activity yet">Your team’s interactions will appear here.</Empty>;
  return <div className="timeline">{activities.map(activity => { const Icon = activity.kind === 'note' ? MessageSquare : activity.kind.includes('assignment') ? GitBranch : activity.kind.includes('task') ? CheckCheck : UserRound; return <article className="timeline-item" key={activity.id}><span className={`timeline-icon ${activity.kind === 'note' ? 'purple' : ''}`}><Icon size={16} /></span><div><div className="timeline-meta"><strong>{compact ? <Link href={`/contacts/${activity.contact}`}>{activity.contact_name}</Link> : label(activity.kind)}</strong><time dateTime={activity.created_at}>{date(activity.created_at)}</time></div><p>{activity.body}</p><small>{activity.actor_name} · {activity.branch_name}</small></div></article>; })}</div>;
}
