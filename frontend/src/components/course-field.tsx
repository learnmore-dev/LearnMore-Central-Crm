'use client';
import { useId } from 'react';
import courses from '@/lib/course-catalog.json';
import { Field } from './ui';

export function CourseField({ value, onChange, title = 'Course name', required = false }: {
  value: string;
  onChange: (value: string) => void;
  title?: string;
  required?: boolean;
}) {
  const id = useId();
  const listId = `${id}-courses`;
  const hintId = `${id}-hint`;
  return <div className="course-field">
    <Field title={title}><input list={listId} value={value} onChange={event => onChange(event.target.value)}
      required={required} maxLength={200} autoComplete="off" placeholder="Search or choose a course"
      aria-describedby={hintId} /></Field>
    <datalist id={listId}>{courses.map(course => <option key={course} value={course} />)}</datalist>
    <small id={hintId} className="muted small-text">Choose a course from the list or type a custom course name.</small>
  </div>;
}
