'use client';
import Link from 'next/link';
import { Badge, Empty } from './ui';
import { date } from '@/lib/format';
import type { Assignment } from '@/lib/types';
export function AssignmentList({ rows }: { rows: Assignment[] }) {
  if (!rows.length) return <Empty title="No assignment history yet">Routing events will appear here as enquiries are assigned.</Empty>;
  return <div className="table-wrap"><table><thead><tr><th>Enquiry</th><th>Assignment</th><th>Event</th><th>Reason & actor</th><th>Time</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><Link className="text-link" href={`/leads/${row.lead}`}>{row.lead_label}</Link><small className="cell-line muted">{row.branch_name} · v{row.version}</small></td><td><span className="muted">{row.previous_owner_name || 'Unassigned'}</span><span className="cell-line">→ {row.new_owner_name || 'Unassigned queue'}</span></td><td><Badge value={row.status} /></td><td className="reason-cell">{row.reason}<small className="cell-line muted">{row.actor_name}</small></td><td className="muted">{date(row.created_at)}</td></tr>)}</tbody></table></div>;
}
