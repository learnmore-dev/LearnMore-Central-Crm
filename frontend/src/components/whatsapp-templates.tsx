'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { date } from '@/lib/format';
import { useList, useRecord } from './data';
import { useUser } from './providers';
import { Badge, Empty, ErrorState, Field, FormError, Loading, PageHeader, Pagination } from './ui';

type Template = { id: string; name: string; language: string; category: string; status: string; body: string; parameter_count: number; supported: boolean; source_mode: string; synced_at: string };
type Account = { id: string; name: string; is_active: boolean };
type Settings = { mode: string; access_token_configured: boolean; graph_version: string };
const categories = [['UTILITY', 'Utility'], ['MARKETING', 'Marketing'], ['AUTHENTICATION', 'Authentication'], ['OTHER', 'Uncategorized / other']];
const statuses = [['APPROVED', 'Approved'], ['PENDING', 'Pending'], ['REJECTED', 'Rejected'], ['PAUSED', 'Paused'], ['DISABLED', 'Disabled'], ['IN_APPEAL', 'In appeal'], ['PENDING_DELETION', 'Pending deletion'], ['DELETED', 'Deleted'], ['MISSING', 'Missing from Meta'], ['OTHER', 'Other statuses']];

function TemplateFilter({ title, options, selected, onChange }: { title: string; options: string[][]; selected: string[]; onChange: (values: string[]) => void }) {
  return <details className="template-filter" name="whatsapp-template-filters"><summary>{title}: {selected.length === 0 ? 'All' : selected.length === 1 ? options.find(([value]) => value === selected[0])?.[1] : `${selected.length} selected`}<ChevronDown size={16} aria-hidden="true" /></summary><fieldset><legend className="sr-only">{title}</legend><label className="check-label"><input type="checkbox" checked={!selected.length} onChange={() => onChange([])} /> All {title === 'Category' ? 'categories' : 'statuses'}</label>{options.map(([value, name]) => <label className="check-label" key={value}><input type="checkbox" checked={selected.includes(value)} onChange={event => onChange(event.target.checked ? [...selected, value] : selected.filter(item => item !== value))} /> {name}</label>)}</fieldset></details>;
}

export function WhatsAppTemplates() {
  const user = useUser(); const client = useQueryClient();
  const [page, setPage] = useState(1); const [channel, setChannel] = useState('');
  const [category, setCategory] = useState<string[]>([]); const [status, setStatus] = useState<string[]>([]);
  const [message, setMessage] = useState('');
  const accounts = useList<Account>('/whatsapp/channels/'); const settings = useRecord<Settings>('/whatsapp/settings/');
  const rows = useList<Template>('/whatsapp/templates/', { page, channel, category: category.join(','), status: status.join(',') });
  function refresh() { void client.invalidateQueries({ predicate: query => query.queryKey[0] === 'list' && String(query.queryKey[1]).startsWith('/whatsapp/templates/') }); }
  const mock = useMutation({ mutationFn: () => api(`/whatsapp/channels/${channel}/mock-template/`, { method: 'POST' }), onSuccess: () => { setPage(1); refresh(); setMessage('Simulation template installed. It is not a Meta-approved template.'); } });
  const sync = useMutation({ mutationFn: () => api<{ count: number; synced_at: string }>('/whatsapp/templates/sync/', { method: 'POST', body: { channel } }), onSuccess: result => { setPage(1); refresh(); setMessage(`${result.count} templates synced from Meta · ${date(result.synced_at)}. No messages sent.`); } });
  const busy = mock.isPending || sync.isPending;
  const filtered = category.length > 0 || status.length > 0;
  return <><PageHeader title="Message templates" description="Browse Utility, Marketing and Authentication templates with their latest synced Meta approval status."><a className="button secondary" href="https://business.facebook.com/" target="_blank" rel="noopener noreferrer">Open Meta Business Suite</a></PageHeader>
    <div className="notice call-integration-notice"><strong>Templates and approvals come from Meta</strong><p>Create and manage templates in WhatsApp Manager, then sync the selected business account here. Category filters do not create or reclassify templates. Mock templates are simulation data.</p><p className="small-text">Syncing is read-only and works without enabling live sends. Templates with unsupported media, buttons or authentication components remain visible but cannot be sent by the current text-only template sender.</p></div>
    <section className="template-controls" aria-label="Template controls"><Field title="Business account"><select value={channel} disabled={busy} onChange={event => { setChannel(event.target.value); setPage(1); setMessage(''); sync.reset(); mock.reset(); }}><option value="">All authorized accounts</option>{accounts.data?.results.map(account => <option key={account.id} value={account.id} disabled={!account.is_active}>{account.name}{account.is_active ? '' : ' · inactive'}</option>)}</select></Field>
      <div className="template-filter-actions"><TemplateFilter title="Category" options={categories} selected={category} onChange={values => { setCategory(values); setPage(1); }} /><TemplateFilter title="Status" options={statuses} selected={status} onChange={values => { setStatus(values); setPage(1); }} />{filtered && <button className="button secondary small" onClick={() => { setCategory([]); setStatus([]); setPage(1); }}>Clear filters</button>}</div>
      {user.capabilities.global_scope && <div className="template-sync-actions"><button className="button primary" disabled={!channel || busy || !settings.data?.access_token_configured || !settings.data?.graph_version} onClick={() => { setMessage(''); sync.mutate(); }}><RefreshCw size={15} className={sync.isPending ? 'spin' : undefined} />{sync.isPending ? 'Syncing from Meta…' : 'Sync from Meta'}</button>{settings.data?.mode === 'mock' && <button className="button secondary" disabled={!channel || busy} onClick={() => mock.mutate()}>Install mock template</button>}</div>}
    </section>
    {user.capabilities.global_scope && settings.data && (!settings.data.access_token_configured || !settings.data.graph_version) && <p className="template-connection-hint">Configure a Meta access token and Graph API version in <Link className="text-link" href="/whatsapp/settings">WhatsApp Settings</Link> to sync real templates.</p>}
    {message && <p className="notice call-integration-notice" role="status">{message}</p>}<FormError error={sync.error || mock.error || accounts.error || settings.error} />
    <section className="panel"><div className="panel-toolbar"><span className="muted small-text">{filtered ? 'Showing templates matching your category and status filters.' : 'All categories and approval statuses.'} Select a business account before syncing.</span><button className="button secondary small" disabled={rows.isFetching} onClick={() => void rows.refetch()}>Refresh list</button></div>
      {rows.isPending ? <Loading /> : rows.error ? <ErrorState error={rows.error} retry={() => void rows.refetch()} /> : rows.data && <>{rows.data.results.length ? <div className="table-wrap"><table className="whatsapp-template-table"><thead><tr><th>Template</th><th>Category</th><th>Content</th><th>Approval</th><th>Source / last sync</th></tr></thead><tbody>{rows.data.results.map(template => <tr key={template.id}><td><strong>{template.name}</strong><small className="cell-line">{template.language} · {template.parameter_count} parameters</small></td><td><Badge value={(template.category || 'uncategorized').toLowerCase()}>{categories.find(([value]) => value === template.category)?.[1] || template.category || 'Uncategorized'}</Badge></td><td className="wa-wrap-cell">{template.body || 'No text body'}</td><td><Badge value={template.status.toLowerCase()}>{template.source_mode === 'mock' ? 'Simulation only' : template.status}</Badge><small className="cell-line">{template.supported ? 'Supported text format' : 'View only · unsupported components'}</small></td><td>{template.source_mode === 'live' ? 'Meta' : template.source_mode === 'mock' ? 'Simulation' : 'Not synced'}<small className="cell-line">{date(template.synced_at)}</small></td></tr>)}</tbody></table></div> : <Empty title={filtered ? 'No templates match these filters' : 'No templates synced'}>{filtered ? 'Change the category or approval status, or clear filters to view every template.' : 'Select an account and sync templates from Meta. Mock templates are available for simulation only.'}</Empty>}<Pagination page={page} count={rows.data.count} next={!!rows.data.next} previous={!!rows.data.previous} onPage={setPage} /></>}
    </section></>;
}
