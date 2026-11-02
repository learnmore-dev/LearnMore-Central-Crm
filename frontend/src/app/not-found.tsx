import Link from 'next/link';
export default function NotFound() { return <div className="empty"><h1>Page not found</h1><p>This page may have moved, or it is outside your workspace.</p><Link className="button secondary" href="/">Return to overview</Link></div>; }
