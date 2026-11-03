import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { WhatsAppTemplates } from '@/components/whatsapp-templates';

const identity = vi.hoisted(() => ({ admin: true, connected: true }));
vi.mock('@/components/providers', () => ({ useUser: () => ({ capabilities: { global_scope: identity.admin } }) }));
vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()), api: vi.fn() }));
const template = { id:'real',name:'demo_reminder',category:'UTILITY',status:'APPROVED',language:'en_US',body:'Your demo is scheduled',parameter_count:0,supported:true,source_mode:'live',synced_at:'2026-11-03T10:00:00Z' };
const paged = (results: unknown[]) => ({count:results.length,next:null,previous:null,results});
function wrap() { return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><WhatsAppTemplates /></QueryClientProvider>); }
beforeEach(()=>{
  identity.admin=true;identity.connected=true;vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async path=>{
    if(path==='/whatsapp/settings/')return {mode:'mock',access_token_configured:identity.connected,graph_version:identity.connected?'v25.0':''};
    if(path==='/whatsapp/channels/')return paged([{id:'channel',name:'Central',is_active:true}]);
    if(path==='/whatsapp/templates/sync/')return {count:2,synced_at:'2026-11-03T10:00:00Z'};
    return paged([template,{...template,id:'mock',name:'mock_welcome',category:'',source_mode:'mock'}]);
  });
});

describe('Meta template catalogue',()=>{
  it('shows Meta categories and distinguishes real approvals from simulation templates',async()=>{
    wrap();
    const row=await screen.findByRole('row',{name:/demo_reminder/});
    expect(within(row).getByText('Utility')).toBeInTheDocument();
    expect(within(row).getByText('APPROVED')).toBeInTheDocument();
    expect(within(row).getByText('Meta')).toBeInTheDocument();
    const mock=screen.getByRole('row',{name:/mock_welcome/});
    expect(within(mock).getByText('Simulation only')).toBeInTheDocument();
    expect(within(mock).getByText('Uncategorized')).toBeInTheDocument();
    expect(within(mock).queryByText('APPROVED')).not.toBeInTheDocument();
  });

  it('combines category and approval filters across server-side pagination',async()=>{
    wrap();const user=userEvent.setup();
    await screen.findByText('demo_reminder');
    await user.click(screen.getByText('Category: All'));
    await user.click(within(screen.getByRole('group',{name:'Category'})).getByRole('checkbox',{name:'Utility'}));
    await user.click(within(screen.getByRole('group',{name:'Category'})).getByRole('checkbox',{name:'Marketing'}));
    await user.click(screen.getByText('Status: All'));
    await user.click(within(screen.getByRole('group',{name:'Status'})).getByRole('checkbox',{name:'Approved'}));
    await user.click(within(screen.getByRole('group',{name:'Status'})).getByRole('checkbox',{name:'Pending'}));
    await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([path])=>{
      const url=new URL(path,'https://crm.example');
      return url.pathname==='/whatsapp/templates/'&&url.searchParams.get('category')==='UTILITY,MARKETING'&&url.searchParams.get('status')==='APPROVED,PENDING'&&url.searchParams.get('page')==='1';
    })).toBe(true));
    await user.click(screen.getByRole('button',{name:'Clear filters'}));
    expect(screen.getByText('Category: All')).toBeInTheDocument();
    expect(screen.getByText('Status: All')).toBeInTheDocument();
  });

  it('syncs the selected account in mock mode without enabling sending',async()=>{
    wrap();const user=userEvent.setup();
    await screen.findByRole('option',{name:'Central'});
    const sync=screen.getByRole('button',{name:'Sync from Meta'});
    expect(sync).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Business account'),'channel');
    await user.click(sync);
    await waitFor(()=>expect(api).toHaveBeenCalledWith('/whatsapp/templates/sync/',{method:'POST',body:{channel:'channel'}}));
    expect(await screen.findByRole('status')).toHaveTextContent('2 templates synced from Meta');
    expect(screen.getByRole('status')).toHaveTextContent('No messages sent');
    expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('/messages/'))).toBe(false);
  });

  it('requires configured credentials and hides sync controls for regular staff',async()=>{
    identity.connected=false;const first=wrap();
    expect(await screen.findByRole('button',{name:'Sync from Meta'})).toBeDisabled();
    expect(await screen.findByRole('link',{name:'WhatsApp Settings'})).toBeInTheDocument();
    first.unmount();identity.admin=false;wrap();
    await screen.findByText('demo_reminder');
    expect(screen.queryByRole('button',{name:'Sync from Meta'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Install mock template'})).not.toBeInTheDocument();
  });
});
