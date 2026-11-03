'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { CourseField } from './course-field';
import { Field, FormError } from './ui';

export type LearningPreferences = { course_interest: string; course_interests: string[]; training_mode: string; city: string; preferred_branch: string | null };
export function learningPreferences(data: Partial<LearningPreferences> | null | undefined, primary = ''): LearningPreferences {
  const course = data?.course_interest || primary;
  return { course_interest: course, course_interests: data?.course_interests?.length ? data.course_interests : course ? [course] : [], training_mode: data?.training_mode || 'undecided', city: data?.city || '', preferred_branch: data?.preferred_branch || null };
}
export function LearningPreferenceFields({ value, onChange }: { value: LearningPreferences; onChange: (value: LearningPreferences) => void }) {
  const [additional, setAdditional] = useState('');
  const [error, setError] = useState('');
  const branches = useQuery({ queryKey: ['preferred-branches'], queryFn: ({ signal }) => api<{ id: string; name: string }[]>('/education/preferred-branches/', { signal }) });
  const interests = Array.from(new Set([value.course_interest.trim(), ...value.course_interests].filter(Boolean)));
  function primary(course: string) {
    onChange({ ...value, course_interest: course, course_interests: [course.trim(), ...interests.filter(item => item !== value.course_interest.trim())].filter(Boolean) });
  }
  function add() {
    const course = additional.trim();
    if (!course) return;
    if (interests.some(item => item.toLowerCase() === course.toLowerCase())) { setError('This course is already selected.'); return; }
    if (interests.length >= 20) { setError('Select up to 20 course interests.'); return; }
    onChange({ ...value, course_interest: value.course_interest || course, course_interests: [...interests, course] });
    setAdditional(''); setError('');
  }
  function remove(course: string) {
    const remaining = interests.filter(item => item !== course);
    onChange({ ...value, course_interest: value.course_interest.trim() === course ? remaining[0] || '' : value.course_interest, course_interests: remaining });
  }
  return <>
    <div className="enquiry-course-group"><CourseField required value={value.course_interest} onChange={primary} /><p className="muted small-text">Primary course for counselling. Add other interests below.</p>
      {!!interests.length && <ul className="course-interest-tags" aria-label="Selected course interests">{interests.map(course => <li key={course}><span>{course}</span>{course === value.course_interest.trim() ? <strong>Primary</strong> : <button type="button" onClick={() => onChange({ ...value, course_interest: course, course_interests: interests })}>Make primary</button>}<button type="button" aria-label={`Remove ${course}`} onClick={() => remove(course)}>×</button></li>)}</ul>}
      <div className="additional-course-row"><CourseField title="Additional course interest" value={additional} onChange={course => { setAdditional(course); setError(''); }} /><button type="button" className="button secondary" disabled={!additional.trim() || interests.length >= 20} onClick={add}>Add course</button></div>{error && <p className="form-error" role="alert">{error}</p>}
    </div>
    <div className="form-row"><Field title="Training mode"><select value={value.training_mode} onChange={event => onChange({ ...value, training_mode: event.target.value })}><option value="undecided">Undecided</option><option value="online">Online</option><option value="classroom">Classroom</option><option value="hybrid">Hybrid</option></select></Field><Field title="Candidate city"><input aria-label="Candidate city" maxLength={120} value={value.city} placeholder="City where the candidate lives" onChange={event => onChange({ ...value, city: event.target.value })} /></Field></div>
    <Field title="Preferred training branch" hint="Candidate preference only. This does not transfer the enquiry or change the counsellor."><select aria-label="Preferred training branch" value={value.preferred_branch || ''} onChange={event => onChange({ ...value, preferred_branch: event.target.value || null })}><option value="">Not decided</option>{(Array.isArray(branches.data) ? branches.data : []).map(branch => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></Field><FormError error={branches.error} />
  </>;
}
