'use client';
import Link from 'next/link';
import { InboxIdentity, type IntakeConversation } from '@/components/inbox-identity';
import { useSearchParams } from 'next/navigation';
import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageSquare, Plus, Send } from 'lucide-react';
import { api, queryPath } from '@/lib/api';
import { date } from '@/lib/format';
import { useList } from '@/components/data';
import { useUser } from '@/components/providers';
import { Badge, Empty, ErrorState, Field, FormError, Loading, Modal, PageHeader, Pagination } from '@/components/ui';
import type { Branch, Contact, Page } from '@/lib/types';

type Channel = { id: string; name: string; branch_name: string; is_active: boolean };
type Conversation = IntakeConversation & { id: string; channel: string; channel_name: string; branch: string; branch_name: string; wa_id: string; contact: string | null; contact_name: string | null; consent: string; last_inbound_at: string | null; service_window_open: boolean; mode: string; live_sends_enabled: boolean };
type Message = { actor_name?: string | null; id: string; direction: string; kind: string; text: string; template_name: string | null; parameters: string[]; mode: string; queue_status: string; delivery_status: string; attempts: number; error_code: string; occurred_at: string; next_attempt_at: string };
type Template = { id: string; name: string; language: string; body: string; parameter_count: number; status: string; supported: boolean; source_mode: string; synced_at: string };

function useInboxList<T>(path: string, params: Record<string, string | number> = {}) {
  const url = queryPath(path, params);
  return useQuery({ queryKey: ['list', url], queryFn: ({ signal }) => api<Page<T>>(url, { signal }), refetchInterval: 10_000 });
}

function NewConversation({ onClose, onSelect }: { onClose: () => void; onSelect: (id: string) => void }) {
  const client = useQueryClient();
  const channels = useList<Channel>('/whatsapp/channels/');
  const [channel, setChannel] = useState('');
  const [phone, setPhone] = useState('');
  const create = useMutation({ mutationFn: () => api<Conversation>('/whatsapp/conversations/', { method: 'POST', body: { channel, wa_id: phone } }),
    onSuccess: row => { void client.invalidateQueries({ queryKey: ['list'] }); onSelect(row.id); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); create.mutate(); }}>
    <Field title="Business inbox"><select required value={channel} onChange={e => setChannel(e.target.value)}><option value="">Choose inbox</option>{channels.data?.results.filter(c => c.is_active).map(c => <option key={c.id} value={c.id}>{c.name} · {c.branch_name}</option>)}</select></Field>
    <Field title="WhatsApp number" hint="International country code and digits, without + or spaces."><input required inputMode="tel" pattern="[1-9][0-9]{6,14}" value={phone} onChange={e => setPhone(e.target.value)} /></Field>
    <p className="muted">Creating a conversation sends no message. Record consent before using an approved template.</p>
    <FormError error={channels.error || create.error} /><button className="button primary" disabled={!channel || create.isPending}>Open conversation</button>
  </form>;
}

function ChannelForm({ onClose }: { onClose: () => void }) {
  const client = useQueryClient(); const branches = useList<Branch>('/branches/');
  const [name, setName] = useState(''); const [branch, setBranch] = useState(''); const [phone, setPhone] = useState(''); const [waba, setWaba] = useState('');
  const save = useMutation({ mutationFn: () => api('/whatsapp/channels/', { method: 'POST', body: { name, branch, phone_number_id: phone, waba_id: waba } }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['list'] }); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
    <Field title="Inbox name"><input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></Field>
    <Field title="Branch"><select required value={branch} onChange={e => setBranch(e.target.value)}><option value="">Choose branch</option>{branches.data?.results.filter(b => b.is_active).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>
    <Field title="Meta phone number ID"><input required pattern="[0-9]{1,40}" value={phone} onChange={e => setPhone(e.target.value)} /></Field>
    <Field title="WhatsApp Business Account ID"><input required pattern="[0-9]{1,40}" value={waba} onChange={e => setWaba(e.target.value)} /></Field>
    <FormError error={branches.error || save.error} /><button className="button primary" disabled={save.isPending}>Add business inbox</button>
  </form>;
}

function ConsentForm({ conversation, onClose }: { conversation: Conversation; onClose: () => void }) {
  const client = useQueryClient(); const [state, setState] = useState('revoked'); const [evidence, setEvidence] = useState('');
  const save = useMutation({ mutationFn: () => api(`/whatsapp/conversations/${conversation.id}/consent/`, { method: 'POST', body: { state, evidence } }), onSuccess: () => { void client.invalidateQueries(); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
    <Field title="Consent decision"><select value={state} onChange={e => setState(e.target.value)}><option value="revoked">Customer opted out</option><option value="granted">Customer explicitly opted in</option></select></Field>
    <Field title="Evidence" hint="Record when, where and how the customer gave or revoked permission."><textarea required maxLength={1000} value={evidence} onChange={e => setEvidence(e.target.value)} /></Field>
    <FormError error={save.error} /><button className="button primary" disabled={!evidence.trim() || save.isPending}>Record consent</button>
  </form>;
}

function ContactLinkForm({ conversation, onClose }: { conversation: Conversation; onClose: () => void }) {
  const client = useQueryClient(); const [search, setSearch] = useState(''); const [contact, setContact] = useState('');
  const contacts = useList<Contact>('/contacts/', { search });
  const link = useMutation({ mutationFn: () => api(`/whatsapp/conversations/${conversation.id}/link/`, { method: 'POST', body: { contact } }), onSuccess: () => { void client.invalidateQueries(); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); link.mutate(); }}>
    <Field title="Find contact"><input value={search} onChange={e => { setSearch(e.target.value); setContact(''); }} placeholder="Contact name or readable ID" maxLength={200} /></Field>
    <Field title="Contact"><select required value={contact} onChange={e => setContact(e.target.value)}><option value="">Choose a contact in this branch</option>{contacts.data?.results.filter(c => c.branch === conversation.branch).map(c => <option key={c.id} value={c.id}>{c.full_name} · {c.contact_id}</option>)}</select></Field>
    <p className="muted">Confirm the customer’s identity before linking. Existing contact links cannot be replaced.</p>
    <FormError error={contacts.error || link.error} /><button className="button primary" disabled={!contact || link.isPending}>Link contact</button>
  </form>;
}

function Composer({ conversation }: { conversation: Conversation }) {
  const client = useQueryClient(); const [text, setText] = useState(''); const [templateId, setTemplateId] = useState(''); const [parameters, setParameters] = useState<string[]>([]);
  const templates = useInboxList<Template>('/whatsapp/templates/', { channel: conversation.channel });
  const canned = useInboxList<{ id: string; title: string; body: string }>('/whatsapp/canned-messages/', { branch: conversation.branch, active: 'true' });
  const selected = templates.data?.results.find(t => t.id === templateId);
  const request = useRef<{ signature: string; key: string } | null>(null);
  const send = useMutation({ mutationFn: () => {
    if (templateId && !selected) throw new Error('The selected template is unavailable. Choose an approved template again.');
    const body = selected ? { template: selected.id, parameters } : { text };
    const signature = JSON.stringify(body);
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    return api('/whatsapp/messages/', { method: 'POST', body: { conversation: conversation.id, client_key: request.current.key, ...body } });
  }, onSuccess: () => { request.current = null; setText(''); setParameters([]); setTemplateId(''); void client.invalidateQueries(); } });
  const disabled = conversation.consent === 'revoked' || (conversation.mode === 'live' && !conversation.live_sends_enabled);
  const valid = templateId ? selected?.status === 'APPROVED' && conversation.consent === 'granted' && parameters.length === selected.parameter_count && parameters.every(p => p.trim()) : conversation.service_window_open && text.trim();
  return <form className="inbox-composer" onSubmit={e => { e.preventDefault(); send.mutate(); }}>
    {conversation.mode === 'mock' ? <div className="notice">Mock mode · queued messages are simulated. No WhatsApp message will be sent.</div> : !conversation.live_sends_enabled && <div className="notice">Live sends are disabled pending approval.</div>}
    {!conversation.service_window_open && <p className="muted">The 24-hour service window is closed. An approved template and explicit consent are required.</p>}
    {conversation.consent === 'revoked' && <p className="form-error">This customer opted out. Sending is blocked.</p>}
    <Field title="Message type"><select value={templateId} disabled={send.isPending} onChange={e => { setTemplateId(e.target.value); const row = templates.data?.results.find(t => t.id === e.target.value); setParameters(Array(row?.parameter_count || 0).fill('')); }}><option value="">Free-form reply</option>{templates.data?.results.filter(t => t.status === 'APPROVED' && t.supported && t.source_mode === conversation.mode).map(t => <option key={t.id} value={t.id}>{t.name} · {t.language}</option>)}</select></Field>
    {!templateId && <Field title="Insert canned reply"><select value="" disabled={send.isPending || disabled || !conversation.service_window_open} onChange={e => { const item = canned.data?.results.find(c => c.id === e.target.value); if (item) setText(item.body); }}><option value="">Choose saved reply</option>{canned.data?.results.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></Field>}
    {selected ? <><p className="template-preview">{selected.body}</p>{Array.from({ length: selected.parameter_count }, (_, i) => <Field key={i} title={`Template parameter ${i + 1}`}><input required maxLength={1024} value={parameters[i] || ''} disabled={send.isPending} onChange={e => setParameters(previous => previous.map((p, index) => index === i ? e.target.value : p))} /></Field>)}{conversation.consent !== 'granted' && <p className="form-error">Record explicit consent to use a template.</p>}</> : <Field title="Reply"><textarea maxLength={4096} value={text} disabled={disabled || !conversation.service_window_open || send.isPending} onChange={e => setText(e.target.value)} placeholder="Write a reply…" /></Field>}
    <FormError error={templates.error || canned.error || send.error} />{send.isSuccess && <p role="status">Message queued. Delivery status appears in the conversation.</p>}
    <button className="button primary" disabled={disabled || !valid || send.isPending}><Send size={16} />{send.isPending ? 'Queueing…' : conversation.mode === 'mock' ? 'Queue mock message' : 'Queue WhatsApp message'}</button>
  </form>;
}

function Thread({ id }: { id: string }) {
  const user = useUser();
  const [page, setPage] = useState(1); const [consent, setConsent] = useState(false); const [linking, setLinking] = useState(false);
  const conversation = useQuery({ queryKey: ['record', `/whatsapp/conversations/${id}/`], queryFn: ({ signal }) => api<Conversation>(`/whatsapp/conversations/${id}/`, { signal }), refetchInterval: 10_000 });
  const messages = useInboxList<Message>('/whatsapp/messages/', { conversation: id, page });
  if (conversation.isPending) return <Loading />;
  if (conversation.error) return <ErrorState error={conversation.error} retry={() => void conversation.refetch()} />;
  const row = conversation.data;
  return <section className="panel inbox-thread"><div className="panel-head"><div><h2>{row.contact_name || '+' + row.wa_id}</h2><p>{row.channel_name} · {row.branch_name}</p>{row.contact && <Link className="text-link" href={`/contacts/${row.contact}`}>Contact profile</Link>}</div><button className="button secondary small" onClick={() => setConsent(true)}>Record consent</button></div>
    <div className="inbox-window"><Badge value={row.service_window_open ? 'active' : 'inactive'}>{row.service_window_open ? 'Service window open' : 'Service window closed'}</Badge><span>Consent: {row.consent} · Last inbound: {date(row.last_inbound_at)}</span></div>
    <InboxIdentity conversation={row} />{messages.isPending ? <Loading /> : messages.error ? <ErrorState error={messages.error} retry={() => void messages.refetch()} /> : messages.data && <><div className="message-list">{messages.data.results.length ? [...messages.data.results].reverse().map(message => <article key={message.id} className={`message-bubble ${message.direction}`}><small>{message.direction === 'inbound' ? 'Customer' : `${message.actor_name || 'Team'}${message.mode === 'mock' ? ' · mock' : ''}`}</small><p>{message.text || `Template: ${message.template_name}`}</p>{message.parameters.length > 0 && <p>{message.parameters.join(' · ')}</p>}<small>{date(message.occurred_at)} · {message.delivery_status || message.queue_status}</small>{message.queue_status === 'retry' && <small>Retry {date(message.next_attempt_at)} · attempt {message.attempts}</small>}{message.error_code && <small className="form-error">{message.error_code}</small>}{message.queue_status === 'unknown' && <p>Delivery outcome is unknown. Check with an administrator before creating another message.</p>}</article>) : <Empty title="No messages yet">Use an approved template to start a conversation after recording consent.</Empty>}</div><Pagination page={page} count={messages.data.count} next={!!messages.data.next} previous={!!messages.data.previous} onPage={setPage} /></>}
    {!row.contact && row.identity_status !== 'review' && user.capabilities.manage_routing && <div className="inbox-window"><button className="button secondary small" onClick={() => setLinking(true)}>Link existing contact</button></div>}
    <Composer conversation={row} />{consent && <Modal title="Record WhatsApp consent" onClose={() => setConsent(false)}><ConsentForm conversation={row} onClose={() => setConsent(false)} /></Modal>}
    {linking && <Modal title="Link WhatsApp contact" onClose={() => setLinking(false)}><ContactLinkForm conversation={row} onClose={() => setLinking(false)} /></Modal>}
  </section>;
}

export default function InboxPage() {
  const user = useUser();
  if (!(user.capabilities.global_scope || ['counsellor', 'branch_manager', 'support'].includes(user.role))) return <Empty title="Messaging access is required" />;
  return <InboxWorkspace />;
}

function InboxWorkspace() {
  const initialConversation = useSearchParams().get('conversation') || '';
  const user = useUser(); const [page, setPage] = useState(1); const [search, setSearch] = useState(''); const [selected, setSelected] = useState(initialConversation); const [creating, setCreating] = useState(false); const [channelForm, setChannelForm] = useState(false);
  const [mine, setMine] = useState(user.role === 'counsellor');
  const conversations = useInboxList<Conversation>('/whatsapp/conversations/', { page, search, mine: mine ? 'true' : '' });
  return <><PageHeader eyebrow="EVERY CONVERSATION, CONNECTED" title="Shared WhatsApp inbox" description="Reply together, follow delivery progress and respect each customer’s preferences.">{user.capabilities.global_scope && <button className="button secondary" onClick={() => setChannelForm(true)}>Add business inbox</button>}<button className="button primary" onClick={() => setCreating(true)}><Plus size={16} /> New conversation</button></PageHeader>
    <div className="inbox-grid"><section className="panel inbox-conversations"><div className="panel-head"><Field title="Find conversation"><input type="search" placeholder="Name, phone, Contact ID or Enquiry ID" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /></Field></div><div className="inbox-window"><label className="check-label"><input type="checkbox" checked={mine} onChange={e => { setMine(e.target.checked); setPage(1); setSelected(''); }} /> Assigned to me</label><span>Unchecked: shared branch inbox</span></div>{conversations.isPending ? <Loading /> : conversations.error ? <ErrorState error={conversations.error} retry={() => void conversations.refetch()} /> : conversations.data && <>{conversations.data.results.length ? <div className="conversation-list">{conversations.data.results.map(row => <button className={`conversation-row ${selected === row.id ? 'selected' : ''}`} aria-pressed={selected === row.id} key={row.id} onClick={() => setSelected(row.id)}><MessageSquare size={18} /><span><strong>{row.contact_name || '+' + row.wa_id}</strong><small>{row.channel_name} · {row.branch_name}</small><small>{row.contact_label || 'Contact pending'} · {row.ownership?.owner_name || 'Unassigned'}</small><small>Consent: {row.consent}</small></span></button>)}</div> : <Empty title="No conversations yet">Signed incoming WhatsApp messages will appear here.</Empty>}<Pagination count={conversations.data.count} page={page} next={!!conversations.data.next} previous={!!conversations.data.previous} onPage={setPage} /></>}</section>
    {selected ? <Thread key={selected} id={selected} /> : <section className="panel"><Empty title="Choose a conversation">Open a customer conversation to view messages and queue a reply.</Empty></section>}</div>
    {creating && <Modal title="New WhatsApp conversation" onClose={() => setCreating(false)}><NewConversation onClose={() => setCreating(false)} onSelect={setSelected} /></Modal>}
    {channelForm && <Modal title="Add business inbox" onClose={() => setChannelForm(false)}><ChannelForm onClose={() => setChannelForm(false)} /></Modal>}
  </>;
}
