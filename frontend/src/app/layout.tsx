import type { Metadata } from 'next';
import { Suspense } from 'react';
import { Providers } from '@/components/providers';
import { Shell } from '@/components/shell';
import './globals.css';
import './workspace.css';
import './readability.css';
export const metadata: Metadata = { title: { default: 'LearnMore Connect', template: '%s · LearnMore Connect' }, description: 'The LearnMore Technologies staff workspace', robots: { index: false, follow: false } };
export default function RootLayout({ children }: { children: React.ReactNode }) { return <html lang="en"><body><Suspense fallback={<p className="loading">Opening workspace…</p>}><Providers><Shell>{children}</Shell></Providers></Suspense></body></html>; }
