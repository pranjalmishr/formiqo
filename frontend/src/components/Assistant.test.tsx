import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {describe,it,expect,vi,beforeEach} from 'vitest';
import {Assistant} from './Assistant';
import {api} from '../lib/api';
vi.mock('../shell',()=>({useApp:()=>({config:{ai_available:true,ai_provider:'https://test-provider.invalid'}})}));
vi.mock('../lib/api',()=>({api:vi.fn()}));
const reply={mode:'ai',answer:'Review the actual outcome.',citations:[],proposal:{section_id:'summary',original:'Original verified text.',suggested:'Clearer verified text.',notes:[]},revision:2,notice:'Proposed, not applied.'};
beforeEach(()=>vi.mocked(api).mockReset());
async function proposal(){render(<MemoryRouter><Assistant resumeId="synthetic-id"/></MemoryRouter>);vi.mocked(api).mockResolvedValue(reply);fireEvent.change(screen.getByLabelText('Ask a question'),{target:{value:'Improve my summary'}});fireEvent.click(screen.getByRole('button',{name:'Ask assistant'}));await screen.findByText('Review proposed replacement')}
describe('assistant review safeguards',()=>{
 it('rejects without modifying the server draft',async()=>{await proposal();fireEvent.click(screen.getByRole('button',{name:'Reject proposal'}));expect(api).toHaveBeenCalledTimes(1);expect(screen.queryByText('Review proposed replacement')).not.toBeInTheDocument();expect(screen.getByRole('status')).toHaveTextContent('Original content is unchanged')});
 it('requires explicit factual confirmation before applying',async()=>{await proposal();expect(screen.getByRole('button',{name:'Apply reviewed proposal'})).toBeDisabled();fireEvent.click(screen.getByLabelText(/I verified all facts/));expect(screen.getByRole('button',{name:'Apply reviewed proposal'})).toBeEnabled();vi.mocked(api).mockResolvedValue({revision:3});fireEvent.click(screen.getByRole('button',{name:'Apply reviewed proposal'}));await waitFor(()=>expect(api).toHaveBeenCalledWith('/ai/apply-proposal',expect.objectContaining({method:'POST'})));expect(JSON.parse(vi.mocked(api).mock.calls[1][1]!.body as string).facts_confirmed).toBe(true)});
 it('blocks unresolved placeholders in proposed text',async()=>{await proposal();fireEvent.change(screen.getByLabelText('Suggested (editable)'),{target:{value:'Delivered [actual outcome].'}});fireEvent.click(screen.getByLabelText(/I verified all facts/));expect(screen.getByRole('button',{name:'Apply reviewed proposal'})).toBeDisabled()});
});
