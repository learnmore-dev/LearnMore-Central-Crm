'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Branch, Page } from '@/lib/types';
import courses from '@/lib/course-catalog.json';
import { useUser } from './providers';
import { ErrorState, Field, FormError, Loading, Modal } from './ui';

type Starter = {
  key: string; name: string; source: string; description: string; callback_minutes: number;
  acknowledgement_text: string;
  steps: { kind: string; title: string; delay_minutes: number; body?: string }[];
};
type Library = { templates: Starter[]; courses: string[] };
type Installed = { created: number; enabled: number; preserved: number; conflicts: string[] };

function delay(minutes: number) {
  if (minutes >= 1440) return `Day ${Math.round(minutes / 1440)}`;
  return minutes ? `After ${minutes} minutes` : 'On arrival';
}

function InstallForm({ onInstalled }: { onInstalled: (result: Installed) => void }) {
  const user = useUser();
  const client = useQueryClient();
  const [branch, setBranch] = useState(user.branch || '');
  const [enable, setEnable] = useState(false);
  const branches = useQuery({ queryKey: ['automation-branches'], queryFn: ({ signal }) => api<Page<Branch>>('/branches/', { signal }) });
  const save = useMutation({
    mutationFn: () => api<Installed>('/automation/rules/install-starters/', { method: 'POST', body: { branch, enable } }),
    onSuccess: result => { void client.invalidateQueries({ queryKey: ['automation'] }); onInstalled(result); },
  });
  return <form className="form-stack" onSubmit={event => { event.preventDefault(); save.mutate(); }}>
    <p>Add five LearnMore rules: a general course guide plus website, missed-call, WhatsApp and walk-in follow-ups.</p>
    <Field title="Branch"><select required value={branch} onChange={event => setBranch(event.target.value)}><option value="">Choose branch</option>{branches.data?.results.filter(item => item.is_active !== false).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
    <label className="check-label"><input type="checkbox" checked={enable} onChange={event => setEnable(event.target.checked)} /> Enable rules for new enquiries</label>
    <p className="muted small-text">Unchecked rules are saved as drafts. Enabled rules create real staff tasks for new arrivals; message steps remain previews. Hours: Monday–Saturday, 9 am–6 pm IST. Existing rule content and active source rules are preserved. Existing enquiries need manual enrollment.</p>
    <FormError error={branches.error || save.error} />
    <button className="button primary" disabled={!branch || branches.isPending || save.isPending}>{save.isPending ? 'Installing…' : enable ? 'Install & enable rules' : 'Install draft rules'}</button>
  </form>;
}

export function AutomationStarters() {
  const user = useUser();
  const manager = user.capabilities.global_scope || user.role === 'branch_manager';
  const [installing, setInstalling] = useState(false);
  const [installed, setInstalled] = useState<Installed | null>(null);
  const [search, setSearch] = useState('');
  const [copied, setCopied] = useState('');
  const library = useQuery({ queryKey: ['automation', 'starter-library'], queryFn: ({ signal }) => api<Library>('/automation/rules/templates/', { signal }), staleTime: 300000 });
  const matches = courses.filter(course => course.toLowerCase().includes(search.trim().toLowerCase()));
  async function copyCourses() {
    try {
      await navigator.clipboard.writeText('LearnMore Technologies — IT courses\n' + (library.data?.courses || []).map(course => `• ${course}`).join('\n') + '\nAsk your counsellor for the syllabus, batch availability and course details.');
      setCopied('Course list copied.');
    } catch { setCopied('Could not copy. Select course names from the list below.'); }
  }
  return <section className="panel automation-starters" aria-label="LearnMore starter rules">
    <div className="panel-head"><div><span className="panel-kicker">BUILT FOR LEARNMORE TECHNOLOGIES</span><h2>Ready-to-use enquiry rules</h2><p>Help candidates choose an IT course and give every counsellor a clear next step.</p></div>{manager && <button className="button primary" onClick={() => setInstalling(true)}>Install starter rules</button>}</div>
    {installed && <div className="notice starter-install-result" role="status">{installed.created} rules added · {installed.enabled} enabled · {installed.preserved} existing rules preserved.{installed.conflicts.length > 0 && <p>Already-active rules were kept for: {installed.conflicts.join(', ')}. Conflicting starter rules remain disabled.</p>}</div>}
    {library.isPending ? <Loading text="Loading LearnMore rules…" /> : library.error ? <ErrorState error={library.error} retry={() => void library.refetch()} /> : library.data && <>
      <div className="starter-rule-grid">{library.data.templates.map(template => <article className="starter-rule-card" key={template.key}>
        <span className="starter-source">{template.source === 'all' ? 'All enquiries · fallback' : template.source === 'manual' ? 'Walk-in / manual' : template.source === 'call' ? 'Incoming calls' : template.source === 'whatsapp' ? 'WhatsApp' : 'Website'}</span>
        <h3>{template.name.replace('LearnMore | ', '')}</h3><p>{template.description}</p>
        <details><summary>View sequence & message preview</summary><ol><li><strong>On arrival</strong> — Create a contact task with a {template.callback_minutes}-minute deadline.</li>{template.acknowledgement_text && <li><strong>After 1 minute</strong> — Acknowledgement preview<p className="starter-message">{template.acknowledgement_text}</p></li>}{template.steps.map((step, index) => <li key={index}><strong>{delay(step.delay_minutes)}</strong> — {step.title}{step.kind === 'message' && <><span className="starter-preview-label">Message preview only</span><p className="starter-message">{step.body}</p></>}</li>)}</ol></details>
      </article>)}</div>
      <div className="starter-course-guide"><div className="section-heading"><div><h3>LearnMore IT course guide</h3><p className="muted small-text">Common learning paths to discuss with candidates. Confirm batch availability with the branch.</p></div><button className="button secondary small" onClick={() => void copyCourses()}>Copy course list</button></div><div className="starter-course-tags">{library.data.courses.map(course => <span key={course}>{course}</span>)}</div>{copied && <p className="small-text" role="status">{copied}</p>}
        <details className="starter-course-catalogue"><summary>Browse full course catalogue · {courses.length} entries</summary><Field title="Search course catalogue"><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search Python, cloud, testing…" /></Field><ul aria-label="Course catalogue">{matches.map(course => <li key={course}>{course}</li>)}</ul>{!matches.length && <p className="muted small-text">No matching course. A custom course can still be recorded on an enquiry.</p>}</details>
      </div>
    </>}
    {installing && <Modal title="Install LearnMore starter rules" onClose={() => setInstalling(false)}><InstallForm onInstalled={result => { setInstalled(result); setInstalling(false); }} /></Modal>}
  </section>;
}
