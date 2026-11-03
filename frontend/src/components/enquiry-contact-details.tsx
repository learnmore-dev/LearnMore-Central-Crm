'use client';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Contact } from '@/lib/types';
import { Field, FormError } from './ui';
export function EnquiryContactDetails({ id }: { id: string }) {
  const contact = useQuery({ queryKey: ['record', `/contacts/${id}/`], queryFn: ({ signal }) => api<Contact>(`/contacts/${id}/`, { signal }) });
  const row = contact.data;
  return <fieldset className="enquiry-form-section"><legend>Contact details</legend><Field title="Candidate name"><input readOnly value={row?.full_name || ''} placeholder={contact.isPending ? 'Loading contact…' : 'Name unavailable'} /></Field><div className="form-row"><Field title="Mobile"><input readOnly value={(row?.identifier_records || []).find(item => item.kind === 'phone')?.normalized_value || ''} /></Field><Field title="Email"><input readOnly value={(row?.identifier_records || []).find(item => item.kind === 'email')?.normalized_value || ''} /></Field></div><Link className="text-link" href={`/contacts/${id}`}>Manage contact details and identifiers →</Link><FormError error={contact.error} /></fieldset>;
}
