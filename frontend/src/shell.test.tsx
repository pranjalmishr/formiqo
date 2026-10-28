import {StrictMode} from 'react';
import {act,render,screen,waitFor,fireEvent} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {AppProvider,useApp} from './shell';
import {api,type Config} from './lib/api';
vi.mock('./lib/api',()=>({api:vi.fn()}));
const mocked=vi.mocked(api);
const config={database_backend:'firestore',firebase_project_id:'demo-formiqo'} as Config;
function Child(){const{config,user}=useApp();return <p>Ready: {config?.database_backend} · {user?.name||'guest'}</p>}
beforeEach(()=>mocked.mockReset());

describe('private workspace initialization',()=>{
 it('deduplicates the cookie-setting request under StrictMode and gates private pages',async()=>{
  let resolve!:(value:Config)=>void;
  mocked.mockImplementation(path=>path==='/config'?new Promise<Config>(done=>{resolve=done}):Promise.resolve({user:null}));
  render(<StrictMode><AppProvider><Child/></AppProvider></StrictMode>);
  expect(mocked.mock.calls.filter(([path])=>path==='/config')).toHaveLength(1);
  expect(screen.queryByText(/Ready:/)).not.toBeInTheDocument();
  await act(async()=>resolve(config));
  expect(await screen.findByText('Ready: firestore · guest')).toBeInTheDocument();
  expect(mocked.mock.calls.map(([path])=>path)).toEqual(['/config','/auth/me']);
 });
 it('allows a failed connection to be retried without mounting private pages early',async()=>{
  mocked.mockRejectedValueOnce(new Error('Synthetic connection failure'));
  mocked.mockResolvedValueOnce(config).mockResolvedValueOnce({user:null});
  render(<AppProvider><Child/></AppProvider>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic connection failure');
  expect(screen.queryByText(/Ready:/)).not.toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('button',{name:'Retry connection'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Retry connection'}));
  expect(await screen.findByText('Ready: firestore · guest')).toBeInTheDocument();
 });
});
