import { Suspense } from 'react';
import { DemosPage } from '@/components/demos';
export default function Page() { return <Suspense fallback={<p>Loading demo schedule…</p>}><DemosPage /></Suspense>; }
