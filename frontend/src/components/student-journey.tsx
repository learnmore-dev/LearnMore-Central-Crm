'use client';
import { CourseField } from '@/components/course-field';
import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Lead } from '@/lib/types';
import { label } from '@/lib/format';
import { useRecord } from './data';
import { ErrorState, Field, FormError, Loading, Modal } from './ui';

export type Qualification = { course_interest: string; background: string; training_mode: string; preferred_location: string; preferred_schedule: string; joining_timeline: string; readiness: string; notes: string; missing_fields: string[] };
const choices: Record<string, [string, string][]> = {
  background: [['unknown', 'Not captured'], ['student', 'Student'], ['working', 'Working professional'], ['job_seeker', 'Job seeker'], ['other', 'Other']],
  training_mode: [['undecided', 'Undecided'], ['online', 'Online'], ['classroom', 'Classroom'], ['hybrid', 'Hybrid']],
  preferred_schedule: [['undecided', 'Undecided'], ['weekday', 'Weekday'], ['weekend', 'Weekend'], ['flexible', 'Flexible']],
  joining_timeline: [['undecided', 'Undecided'], ['immediate', 'Immediately'], ['month', 'Within a month'], ['quarter', 'Within three months'], ['later', 'Later']],
  readiness: [['exploring', 'Exploring options'], ['demo_ready', 'Ready for a demo'], ['admission_ready', 'Ready for admission'], ['later', 'Follow up later']],
};

export function QualificationForm({ lead, data, onClose }: { lead: Lead; data: Qualification; onClose: () => void }) {
  const client = useQueryClient();
  const [form, setForm] = useState({ course_interest: data.course_interest || lead.title, background: data.background, training_mode: data.training_mode, preferred_location: data.preferred_location, preferred_schedule: data.preferred_schedule, joining_timeline: data.joining_timeline, readiness: data.readiness, notes: data.notes });
  const save = useMutation({ mutationFn: () => api(`/education/qualifications/${lead.id}/`, { method: 'PATCH', body: form }), onSuccess: () => { void client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' }); onClose(); } });
  return <form className="form-stack" onSubmit={e => { e.preventDefault(); save.mutate(); }}><CourseField title="Course interest" value={form.course_interest} onChange={course_interest => setForm({ ...form, course_interest })} />{Object.entries(choices).map(([key, options]) => <Field key={key} title={label(key)}><select value={form[key as keyof typeof form]} onChange={e => setForm({ ...form, [key]: e.target.value })}>{options.map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></Field>)}<Field title="Preferred branch / location"><input maxLength={120} value={form.preferred_location} onChange={e => setForm({ ...form, preferred_location: e.target.value })} /></Field><Field title="Counselling notes"><textarea maxLength={2000} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></Field><p className="muted small-text">Readiness is the counsellor’s assessment. Saving it does not change the enquiry stage or send a message.</p><FormError error={save.error} /><button className="button primary" disabled={save.isPending}>Save qualification</button></form>;
}

export function StudentJourney({ lead }: { lead: Lead }) {
  const result = useRecord<Qualification>(`/education/qualifications/${lead.id}/`); const [editing, setEditing] = useState(false);
  return <section className="panel"><div className="panel-head"><div><h2>Student learning goals</h2><p>Capture the course fit and plan the next counselling step.</p></div><div className="automation-actions">{result.data && <button className="button secondary small" onClick={() => setEditing(true)}>Update qualification</button>}<Link className="button secondary small" href={`/demos?lead=${lead.id}`}>Demos & attendance</Link></div></div>{result.isPending ? <Loading /> : result.error ? <ErrorState error={result.error} retry={() => void result.refetch()} /> : result.data && <div className="education-details"><div><span>Course interest</span><strong>{result.data.course_interest || 'Not captured'}</strong></div><div><span>Training mode</span><strong>{label(result.data.training_mode)}</strong></div><div><span>Joining timeline</span><strong>{choices.joining_timeline.find(([v]) => v === result.data!.joining_timeline)?.[1]}</strong></div><div><span>Readiness</span><strong>{choices.readiness.find(([v]) => v === result.data!.readiness)?.[1]}</strong></div><p className="muted">{result.data.missing_fields.length ? `Still to capture: ${result.data.missing_fields.map(label).join(', ')}.` : 'Core qualification details captured.'}</p>{result.data.notes && <p className="education-note">{result.data.notes}</p>}</div>}{editing && result.data && <Modal title="Student qualification" onClose={() => setEditing(false)}><QualificationForm lead={lead} data={result.data} onClose={() => setEditing(false)} /></Modal>}</section>;
}
