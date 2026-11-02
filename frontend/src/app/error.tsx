'use client';
import { ErrorState } from '@/components/ui';
export default function PageError({ reset }: { error: Error; reset: () => void }) { return <ErrorState error={new Error('This page could not be displayed. Please try again.')} retry={reset} />; }
