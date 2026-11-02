'use client';
import { useParams, notFound } from 'next/navigation';
import { useUser } from '@/components/providers';
import { Empty } from '@/components/ui';
import { whatsappLinks } from '@/components/whatsapp-nav';
import { WhatsAppWorkspace } from '@/components/whatsapp-workspace';

export default function WhatsAppPage() {
  const { section } = useParams<{ section: string }>();
  const user = useUser();
  if (!whatsappLinks.some(([slug]) => slug === section)) notFound();
  if (!(user.capabilities.global_scope || ['branch_manager', 'counsellor', 'support'].includes(user.role))) return <Empty title="Messaging access is required" />;
  return <WhatsAppWorkspace key={section} section={section} />;
}
