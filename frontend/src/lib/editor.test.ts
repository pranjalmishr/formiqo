import { describe,it,expect } from 'vitest';
import { htmlText,textHTML,draftText,snapshot } from './editor';
describe('section content helpers',()=>{
 it('extracts consistent nested bullet text',()=>expect(htmlText('<ul><li><p>Built services</p></li><li><p>Tested tools</p></li></ul>')).toContain('• Built services'));
 it('never treats AI text as executable HTML',()=>expect(textHTML('<script>alert(1)</script>')).not.toContain('<script>'));
 it('preserves multiline replacement bullets',()=>{const html=textHTML('• Built verified tools\n• Tested verified tools');expect(html).toContain('<ul>');expect(htmlText(html)).toContain('• Tested verified tools')});
 it('preserves section order and avoids a contact heading',()=>{const text=draftText([{id:'a',title:'Contact information',html:'<p>Jordan</p>'},{id:'b',title:'Projects',html:'<p>Built tools</p>'}]);expect(text.startsWith('Jordan')).toBe(true);expect(text).not.toContain('Contact information');expect(text).toContain('Projects\nBuilt tools')});
 it('tracks rejected suggestions without changing content',()=>{const sections=[{id:'a',title:'Summary',html:'<p>Original text</p>'}];const snap=JSON.parse(snapshot(sections,[],['rejected-id']));expect(snap.content.sections).toEqual(sections);expect(snap.rejected).toEqual(['rejected-id'])});
});
