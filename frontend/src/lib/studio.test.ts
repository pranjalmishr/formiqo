import {describe,it,expect} from 'vitest';
import {entryGroups,moveEntry,replaceQuotedText,filterTemplates,type TemplateDefinition} from './studio';
import {htmlText} from './editor';
const base={query:'',level:'',profession:'',layout:'',ats:false,compact:false,page:'',focus:'',favoritesOnly:false,favorites:[] as string[],sort:'recommended'};
const templates=[{id:'classic',name:'Classic ATS',description:'Traditional single stream',category:'Classic professional',professions:['General professional'],levels:['Senior'],layout:'single',columns:1,ats_oriented:true,compact:false,focus:'Experience-focused',page_hint:'One or two pages'},{id:'technical',name:'Technical Resume',description:'Project and methods rail',category:'Technical',professions:['Software engineering'],levels:['Student','Entry-level'],layout:'sidebar-right',columns:2,ats_oriented:false,compact:true,focus:'Skills-focused',page_hint:'Two-page friendly'}] as TemplateDefinition[];
describe('actual template filtering',()=>{
 it('searches meaningful metadata rather than decorative controls',()=>expect(filterTemplates(templates,{...base,query:'methods'}).map(t=>t.id)).toEqual(['technical']));
 it('combines career, profession, layout and ATS filters',()=>{expect(filterTemplates(templates,{...base,level:'Student',profession:'Software engineering',layout:'sidebar-right'})).toHaveLength(1);expect(filterTemplates(templates,{...base,level:'Student',ats:true})).toHaveLength(0)});
 it('limits favorites to the actual selected IDs',()=>expect(filterTemplates(templates,{...base,favoritesOnly:true,favorites:['technical']}).map(t=>t.id)).toEqual(['technical']));
 it('sorts without changing the original collection',()=>{expect(filterTemplates(templates,{...base,sort:'name'})[0].id).toBe('classic');expect(templates.map(t=>t.id)).toEqual(['classic','technical'])});
});
describe('entry-level editing without content loss',()=>{
 const html='<p>Verified introduction.</p><p><strong>Engineer | Actual Company A</strong></p><p>2021–2023</p><ul><li>Built verified A.</li></ul><p><strong>Engineer | Actual Company B</strong></p><p>2023–Present</p><ul><li>Built verified B.</li></ul>';
 it('detects actual whole-bold entry boundaries and preserves the preface',()=>{const value=entryGroups(html);expect(value.entries).toHaveLength(2);expect(value.preface).toContain('Verified introduction')});
 it('moves dates/bullets with their entry and retains all source text',()=>{const moved=moveEntry(html,1,0);expect(moved.indexOf('Company B')).toBeLessThan(moved.indexOf('Company A'));for(const word of ['2021','2023','Built verified A','Built verified B','Verified introduction'])expect(htmlText(moved)).toContain(word)});
 it('rejects invalid ordering without corrupting the source',()=>{expect(moveEntry(html,3,0)).toBe(html);expect(moveEntry(html,0,-1)).toBe(html)});
});
describe('selected-text AI approval helper',()=>{
 it('replaces only the unique quote and preserves adjacent facts/formatting',()=>{const html='<p><strong>Actual Company</strong> — Built verified services for internal reports.</p>';const value=replaceQuotedText(html,'Built verified services','Developed verified services');expect(value).toContain('<strong>Actual Company</strong>');expect(htmlText(value)).toContain('Developed verified services for internal reports.')});
 it('rejects ambiguous repeated quotes rather than choosing arbitrarily',()=>expect(()=>replaceQuotedText('<p>Actual work. Actual work.</p>','Actual work.','Changed.')).toThrow(/ambiguous/));
 it('escapes proposed markup instead of executing it',()=>{const value=replaceQuotedText('<p>Actual work.</p>','Actual work.','<script>bad()</script>');expect(value).not.toContain('<script>');expect(value).toContain('&lt;script&gt;')});
 it('does not overwrite when the source quote is no longer present',()=>expect(()=>replaceQuotedText('<p>Newer source.</p>','Old source.','Replacement.')).toThrow());
});
