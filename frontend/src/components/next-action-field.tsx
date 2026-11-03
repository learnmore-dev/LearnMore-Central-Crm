'use client';
import { useState } from 'react';
import { Field } from './ui';

export const nextActions = [
  'Call candidate',
  'Send course syllabus',
  'Share fees and payment options',
  'Confirm preferred batch timing',
  'Schedule a demo',
  'Follow up after demo',
  'Arrange branch visit',
  'Follow up on admission',
  'Collect enrollment documents',
  'Confirm joining date',
];

export function NextActionField({ value, onChange, required = false, title = 'Next action', hint }: {
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  title?: string;
  hint?: string;
}) {
  const isPreset = nextActions.includes(value);
  const [customMode, setCustomMode] = useState(!!value && !isPreset);
  const [customDraft, setCustomDraft] = useState(isPreset ? '' : value);
  const custom = customMode || (!!value && !isPreset);
  return <div className="next-action-field">
    <Field title={title} hint={hint}>
      <select aria-label={title} required={required} value={custom ? '__custom__' : value} onChange={event => {
        const choice = event.target.value;
        setCustomMode(choice === '__custom__');
        onChange(choice === '__custom__' ? customDraft : choice);
      }}>
        <option value="">{required ? 'Choose next action' : 'Choose next action (optional)'}</option>
        {nextActions.map(action => <option key={action} value={action}>{action}</option>)}
        <option value="__custom__">Custom action…</option>
      </select>
    </Field>
    {custom && <Field title="Custom next action"><input aria-label="Custom next action" required maxLength={500}
      value={value} placeholder="Enter the next follow-up action" onChange={event => {
        setCustomDraft(event.target.value);
        onChange(event.target.value);
      }} /></Field>}
  </div>;
}
