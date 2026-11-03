'use client';
import { useEffect, useRef, type ReactNode } from 'react';
import { AlertCircle, ArrowLeft, ArrowRight, Inbox, LoaderCircle, X } from 'lucide-react';
export function Loading({ text = 'Loading…' }: { text?: string }) { return <div className="loading" role="status"><LoaderCircle className="spin" size={20} /><span>{text}</span></div>; }
export function ErrorState({ error, retry }: { error: Error | null; retry?: () => void }) { return <div className="error-state" role="alert"><AlertCircle size={20} /><div><strong>Something needs attention</strong><p>{error?.message || 'Please try again.'}</p>{retry && <button className="button secondary small" onClick={retry}>Try again</button>}</div></div>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><Inbox size={30} /><h3>{title}</h3>{children && <p>{children}</p>}</div>; }
export function Badge({ value, children }: { value: string; children?: ReactNode }) { return <span className={`badge badge-${value}`}>{children || value.replaceAll('_', ' ')}</span>; }
export function PageHeader({ eyebrow, title, description, children }: { eyebrow?: string; title: string; description: string; children?: ReactNode }) { return <div className="page-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1><p>{description}</p></div><div className="heading-actions">{children}</div></div>; }
export function Pagination({ count, page, next, previous, onPage }: { count: number; page: number; next: boolean; previous: boolean; onPage: (page: number) => void }) { return <div className="pagination"><span>{count.toLocaleString('en-IN')} records · Page {page}</span><div><button className="icon-button" aria-label="Previous page" disabled={!previous} onClick={() => onPage(page - 1)}><ArrowLeft size={17} /></button><button className="icon-button" aria-label="Next page" disabled={!next} onClick={() => onPage(page + 1)}><ArrowRight size={17} /></button></div></div>; }
export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog ref={ref} className={wide ? 'modal modal-wide' : 'modal'} aria-label={title} onCancel={onClose}><div className="modal-head"><h2>{title}</h2><button type="button" className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20} /></button></div>{children}</dialog>;
}
export function FormError({ error }: { error: Error | null }) { return error ? <p className="form-error" role="alert">{error.message}</p> : null; }
export function Field({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) { return <label className="field"><span>{title}</span>{children}{hint && <small>{hint}</small>}</label>; }
