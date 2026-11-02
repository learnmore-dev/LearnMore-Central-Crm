'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useList, useRecord } from './data';
import { useUser } from './providers';
import { date } from '@/lib/format';
import { ErrorState, Field, FormError, Loading, PageHeader } from './ui';

type Configuration = {
  mode: string; live_sends_enabled: boolean; bulk_sends_enabled: boolean;
  access_token_configured: boolean; app_secret_configured: boolean; verify_token_configured: boolean;
  graph_version: string; webhook_path: string; storage_ready: boolean; webhook_url: string; webhook_verified_at: string | null;
};
type Account = { id: string; name: string; branch_name: string; is_active: boolean };
type Check = { connected: boolean; code: string; detail: string; display_phone_number?: string; verified_name?: string };

function CredentialForm({ config, onSaved }: { config: Configuration; onSaved: () => void }) {
  const client = useQueryClient();
  const [version, setVersion] = useState(config.graph_version);
  const [url, setUrl] = useState(config.webhook_url || '');
  const [access, setAccess] = useState('');
  const [secret, setSecret] = useState('');
  const [verify, setVerify] = useState('');
  const [message, setMessage] = useState('');
  const save = useMutation({
    mutationFn: () => api<Configuration>('/whatsapp/settings/', { method: 'PATCH', body: {
      graph_version: version, webhook_url: url,
      ...(access.trim() ? { access_token: access.trim() } : {}),
      ...(secret.trim() ? { app_secret: secret.trim() } : {}),
      ...(verify.trim() ? { verify_token: verify.trim() } : {}),
    } }),
    onSuccess: () => {
      setAccess(''); setSecret(''); setVerify(''); onSaved();
      setMessage('Connection settings saved securely. Live messaging has not been enabled.');
      void client.invalidateQueries({ queryKey: ['record', '/whatsapp/settings/'] });
    },
  });
  function generateToken() {
    const bytes = crypto.getRandomValues(new Uint8Array(24));
    setVerify(Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join(''));
    setMessage('Verification token generated. Copy it into Meta before saving.');
  }
  async function copyToken() {
    try { await navigator.clipboard.writeText(verify); setMessage('Verification token copied. Paste it into Meta, then save these settings.'); }
    catch { setMessage('Clipboard unavailable. Enter a verification token you can also enter in Meta.'); }
  }
  return <form className="form-stack" onSubmit={event => { event.preventDefault(); setMessage(''); save.mutate(); }}>
    <p className="muted">Use credentials from LearnMore’s Meta app. Saved secrets stay hidden; leave a secret blank to keep its current value.</p>
    {!config.storage_ready && <div className="notice">Secure credential storage needs to be configured by your server administrator before settings can be saved.</div>}
    <Field title="Graph API version" hint="Use the supported version shown in your Meta app’s API setup."><input aria-label="Graph API version" required pattern="v[0-9]{1,3}\.[0-9]{1,2}" maxLength={16} placeholder="v…" value={version} onChange={event => setVersion(event.target.value)} /></Field>
    <Field title="Access token" hint={config.access_token_configured ? 'A token is saved. Enter a new token only to replace it.' : 'Use a Meta access token with access to your WhatsApp Business account.'}><input aria-label="Access token" type="password" autoComplete="new-password" maxLength={8192} value={access} onChange={event => setAccess(event.target.value)} placeholder={config.access_token_configured ? 'Configured · leave blank to keep' : 'Paste access token'} /></Field>
    <Field title="Meta app secret" hint="Used to verify signed incoming webhooks."><input aria-label="Meta app secret" type="password" autoComplete="new-password" maxLength={1024} value={secret} onChange={event => setSecret(event.target.value)} placeholder={config.app_secret_configured ? 'Configured · leave blank to keep' : 'Paste app secret'} /></Field>
    <Field title="Webhook verification token" hint="Enter the same token in Meta’s webhook configuration. Copy a generated token before saving; it cannot be retrieved later."><input aria-label="Webhook verification token" type="password" autoComplete="new-password" maxLength={1024} value={verify} onChange={event => setVerify(event.target.value)} placeholder={config.verify_token_configured ? 'Configured · leave blank to keep' : 'Enter or generate a token'} /></Field>
    <div className="automation-actions"><button type="button" className="button secondary small" onClick={generateToken}>Generate verification token</button><button type="button" className="button secondary small" disabled={!verify} onClick={() => void copyToken()}>Copy verification token</button></div>
    <Field title="Public webhook callback URL" hint={`Use your public HTTPS CRM domain followed by ${config.webhook_path}. Localhost is not reachable by Meta.`}><input aria-label="Public webhook callback URL" type="url" maxLength={500} value={url} onChange={event => setUrl(event.target.value)} placeholder={`https://your-crm-domain${config.webhook_path}`} /></Field>
    {message && <p className="notice" role="status">{message}</p>}<FormError error={save.error} />
    <button className="button primary" disabled={!config.storage_ready || save.isPending}>{save.isPending ? 'Saving…' : 'Save connection settings'}</button>
  </form>;
}

export function WhatsAppSettings() {
  const user = useUser();
  const admin = user.capabilities.global_scope;
  const settings = useRecord<Configuration>('/whatsapp/settings/');
  const accounts = useList<Account>('/whatsapp/channels/');
  const [account, setAccount] = useState('');
  const [copyMessage, setCopyMessage] = useState('');
  const check = useMutation({ mutationFn: () => api<Check>('/whatsapp/settings/check/', { method: 'POST', body: { channel: account } }) });
  async function copyCallback() {
    try { await navigator.clipboard.writeText(settings.data?.webhook_url || ''); setCopyMessage('Webhook URL copied.'); }
    catch { setCopyMessage('Could not copy. Select the URL above and copy it manually.'); }
  }
  if (settings.isPending) return <Loading text="Loading WhatsApp setup…" />;
  if (settings.error || !settings.data) return <ErrorState error={settings.error} retry={() => void settings.refetch()} />;
  const config = settings.data;
  return <><PageHeader title="WhatsApp connection setup" description="Connect LearnMore’s business account, check Meta access and configure incoming enquiries." />
    <div className="notice call-integration-notice"><strong>{config.mode === 'mock' ? 'Simulation mode is active' : 'Live provider mode is configured'}</strong><p>Saving credentials and checking the connection do not send messages. Individual live sends are {config.live_sends_enabled ? 'enabled by server configuration' : 'disabled'}. Bulk live sends remain disabled.</p></div>
    <div className="wa-setup-grid"><section className="panel"><div className="panel-head"><div><h2>1. Save Meta connection details</h2><p>Organization administrators manage this shared connection.</p></div></div>{admin ? <CredentialForm config={config} onSaved={() => check.reset()} /> : <div className="form-stack"><p>Ask your organization administrator to configure the Meta credentials. You can view connection readiness below.</p></div>}</section>
      <div><section className="panel"><div className="panel-head"><div><h2>2. Check a business account</h2><p>This reads account details from Meta without sending a message.</p></div></div><div className="form-stack"><Link className="text-link" href="/whatsapp/accounts">Add or manage WhatsApp accounts →</Link>
        {admin && <><Field title="Account to check"><select value={account} onChange={event => { setAccount(event.target.value); check.reset(); }}><option value="">Choose business account</option>{accounts.data?.results.filter(item => item.is_active).map(item => <option value={item.id} key={item.id}>{item.name} · {item.branch_name}</option>)}</select></Field><button className="button secondary" disabled={!account || check.isPending || !config.access_token_configured || !config.graph_version} onClick={() => check.mutate()}>{check.isPending ? 'Checking Meta access…' : 'Check Meta connection'}</button></>}
        {!config.access_token_configured && <p className="muted small-text">Save an access token before running a connection check.</p>}
        {check.data && <div className={check.data.connected ? 'notice' : 'form-error'} role="status"><strong>{check.data.connected ? 'Account access verified' : 'Connection needs attention'}</strong><p>{check.data.detail}</p>{check.data.connected && <p>{check.data.verified_name} {check.data.display_phone_number}</p>}</div>}<FormError error={check.error || accounts.error} />
      </div></section>
      <section className="panel"><div className="panel-head"><div><h2>3. Configure incoming webhooks</h2><p>Use the saved callback URL and the verification token in your Meta app.</p></div></div><div className="form-stack">{config.webhook_url ? <><Field title="Saved callback URL"><input readOnly value={config.webhook_url} /></Field><button className="button secondary small" onClick={() => void copyCallback()}>Copy callback URL</button></> : <p className="muted">Save your public HTTPS callback URL to make it available here.</p>}{copyMessage && <p role="status">{copyMessage}</p>}<p>Verify the callback in Meta and subscribe to WhatsApp <strong>messages</strong> events for incoming messages and delivery updates.</p><p className="muted small-text">{config.webhook_verified_at ? `Last callback challenge accepted: ${date(config.webhook_verified_at)}` : 'No callback challenge has been accepted for this saved configuration yet.'}</p><a className="text-link" href="https://developers.facebook.com/apps/" target="_blank" rel="noopener noreferrer">Open Meta app dashboard →</a></div></section></div>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>Connection readiness</h2><p>Saved settings, account access and incoming webhook delivery are separate checks.</p></div><button className="button secondary small" disabled={settings.isFetching} onClick={() => void settings.refetch()}>Refresh readiness</button></div><div className="form-stack"><dl className="wa-settings-list">{Object.entries({ 'Provider mode': config.mode, 'Access token': config.access_token_configured ? 'Configured (hidden)' : 'Not configured', 'App secret': config.app_secret_configured ? 'Configured (hidden)' : 'Not configured', 'Webhook verification token': config.verify_token_configured ? 'Configured (hidden)' : 'Not configured', 'Graph API version': config.graph_version || 'Not set', 'Webhook route': config.webhook_path, 'Individual live sends': config.live_sends_enabled ? 'Enabled by server configuration' : 'Disabled', 'Bulk live sends': 'Disabled' }).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></div></section>
  </>;
}
