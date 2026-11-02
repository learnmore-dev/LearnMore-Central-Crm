'use client';
import Link from 'next/link';
import { useState } from 'react';
import { ChevronDown, MessageCircle } from 'lucide-react';

export const whatsappLinks = [
  ['campaigns', 'Campaigns'], ['templates', 'Templates'], ['message-trail', 'Message trail'],
  ['canned-messages', 'Canned messages'], ['accounts', 'Accounts'], ['chat-widget', 'Chat widget & QR code'],
  ['ads', 'Ads'], ['settings', 'Settings'],
] as const;

export function WhatsAppNav({ pathname, onNavigate }: { pathname: string; onNavigate: () => void }) {
  const [expanded, setExpanded] = useState(true);
  const active = pathname.startsWith('/whatsapp');
  return <div className="whatsapp-nav-group">
    <button type="button" className={`nav-link whatsapp-nav-toggle ${active ? 'active' : ''}`} aria-expanded={expanded} aria-controls="whatsapp-submenu" onClick={() => setExpanded(!expanded)}>
      <MessageCircle size={19} /><span>WhatsApp</span><ChevronDown size={15} className={expanded ? 'expanded' : ''} />
    </button>
    {expanded && <div id="whatsapp-submenu" className="whatsapp-submenu">{whatsappLinks.map(([slug, name]) => <Link
      href={`/whatsapp/${slug}`} key={slug} aria-current={pathname === `/whatsapp/${slug}` ? 'page' : undefined}
      className={`whatsapp-sub-link ${pathname === `/whatsapp/${slug}` ? 'active' : ''} ${slug === 'accounts' ? 'submenu-divider' : ''}`}
      onClick={onNavigate}>{name}</Link>)}</div>}
  </div>;
}
