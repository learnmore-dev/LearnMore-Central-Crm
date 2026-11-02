'use client';
import { useState } from 'react';
import { useList } from '@/components/data';
import { AssignmentList } from '@/components/assignment-list';
import { ErrorState, Loading, PageHeader, Pagination } from '@/components/ui';
import type { Assignment } from '@/lib/types';
export default function AssignmentsPage() { const [page, setPage] = useState(1); const result = useList<Assignment>('/assignment-history/', { page }); return <><PageHeader eyebrow="CLEAR OWNERSHIP" title="Assignment history" description="A permanent record of ownership, routing decisions and authorized transfers." /><section className="panel">{result.isPending ? <Loading /> : result.error ? <ErrorState error={result.error} retry={() => void result.refetch()} /> : result.data && <><AssignmentList rows={result.data.results} /><Pagination page={page} count={result.data.count} next={!!result.data.next} previous={!!result.data.previous} onPage={setPage} /></>}</section></>; }
