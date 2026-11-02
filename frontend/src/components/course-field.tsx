'use client';
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronDown } from 'lucide-react';
import courses from '@/lib/course-catalog.json';

export function CourseField({ value, onChange, title = 'Course name', required = false }: {
  value: string;
  onChange: (value: string) => void;
  title?: string;
  required?: boolean;
}) {
  const id = useId();
  const listId = `${id}-courses`;
  const hintId = `${id}-hint`;
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [active, setActive] = useState(-1);
  const matches = courses.filter(course => course.toLowerCase().includes(filter.trim().toLowerCase()));

  useLayoutEffect(() => {
    if (!open) return;
    const popup = list.current;
    function position() {
      if (!input.current || !popup) return;
      const rect = (input.current.parentElement || input.current).getBoundingClientRect();
      const below = window.innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const upwards = below < 180 && above > below;
      const height = Math.min(280, Math.max(0, upwards ? above : below));
      Object.assign(popup.style, {
        left: `${rect.left}px`, width: `${rect.width}px`, maxHeight: `${height}px`,
        top: upwards ? 'auto' : `${rect.bottom + 6}px`,
        bottom: upwards ? `${window.innerHeight - rect.top + 6}px` : 'auto',
      });
    }
    position();
    popup?.showPopover?.();
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    return () => {
      popup?.hidePopover?.();
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
    };
  }, [open]);

  useEffect(() => {
    if (open && active >= 0) list.current?.children[active]?.scrollIntoView?.({ block: 'nearest' });
  }, [active, open]);

  function choose(course: string) {
    onChange(course);
    setOpen(false);
    setActive(-1);
    input.current?.focus();
  }
  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) { setFilter(''); setOpen(true); setActive(event.key === 'ArrowDown' ? 0 : courses.length - 1); }
      else setActive(previous => matches.length ? (previous + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length : -1);
    } else if (event.key === 'Enter' && open) {
      event.preventDefault();
      if (active >= 0 && matches[active]) choose(matches[active]);
      else { setOpen(false); setActive(-1); }
    } else if (event.key === 'Escape' && open) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      setActive(-1);
    } else if (event.key === 'Tab') setOpen(false);
  }

  return <div className="course-field">
    <label className="course-label" htmlFor={id}>{title}{required && <span className="required-mark" aria-hidden="true"> *</span>} <small aria-hidden="true">(search, select or add custom)</small></label>
    <div className="course-search-control">
      <input ref={input} id={id} role="combobox" aria-label={title} aria-autocomplete="list" aria-expanded={open}
        aria-controls={listId} aria-activedescendant={open && active >= 0 && matches[active] ? `${id}-option-${active}` : undefined}
        aria-describedby={hintId} value={value} required={required} maxLength={200} autoComplete="off"
        placeholder="Type to search or add custom course…"
        onFocus={() => { setFilter(''); setActive(-1); setOpen(true); }}
        onClick={() => { if (!open) { setFilter(''); setActive(-1); setOpen(true); } }}
        onChange={event => { onChange(event.target.value); setFilter(event.target.value); setActive(-1); setOpen(true); }}
        onBlur={() => { setOpen(false); setActive(-1); }} onKeyDown={keyDown} />
      <button type="button" tabIndex={-1} className="course-search-toggle" aria-label={`Toggle ${title.toLowerCase()} options`}
        aria-expanded={open} aria-controls={listId} onMouseDown={event => event.preventDefault()}
        onClick={() => { if (open) setOpen(false); else { input.current?.focus(); setFilter(''); setActive(-1); setOpen(true); } }}>
        <ChevronDown size={17} aria-hidden="true" />
      </button>
    </div>
    {open && <div ref={list} id={listId} role="listbox" aria-label={`${title} options`} popover={typeof HTMLElement !== 'undefined' && 'showPopover' in HTMLElement.prototype ? 'manual' : undefined} className="course-search-options">
      {matches.map((course, index) => <div key={course} id={`${id}-option-${index}`} role="option"
        aria-selected={value === course} className={active === index ? 'is-highlighted' : undefined}
        onMouseDown={event => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => choose(course)}>{course}</div>)}
      {!matches.length && <div className="course-search-empty" role="status">No matching courses. Your custom course will be saved.</div>}
    </div>}
    <small id={hintId} className="muted small-text">Choose a course or type a custom course name.</small>
  </div>;
}
