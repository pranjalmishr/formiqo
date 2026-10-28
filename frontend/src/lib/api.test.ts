import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, validateFile } from './api';
afterEach(()=>vi.unstubAllGlobals());
describe('upload validation',()=>{
 it('accepts PDF, DOCX and TXT',()=>{for(const ext of ['pdf','docx','txt'])expect(validateFile(new File(['resume'],'CV.'+ext),10)).toBeNull()});
 it('rejects legacy DOC and disguised extensions',()=>{expect(validateFile(new File(['data'],'resume.doc'),10)).toMatch(/Legacy DOC/);expect(validateFile(new File(['data'],'resume.pdf.exe'),10)).toBeTruthy()});
 it('rejects empty or oversized files',()=>{expect(validateFile(new File([],'resume.txt'),10)).toMatch(/empty/);expect(validateFile(new File([new Uint8Array(1024*1024+1)],'resume.pdf'),1)).toMatch(/smaller/)});
});
describe('API errors',()=>{
 it('explains network failures',async()=>{vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));await expect(api('/config')).rejects.toThrow(/Cannot reach/)});
 it('preserves server validation messages',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:415,json:async()=>({detail:'Unsupported format'})}));await expect(api('/resumes')).rejects.toThrow('Unsupported format')});
 it('uses private session credentials',async()=>{const fetch=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>({items:[]})});vi.stubGlobal('fetch',fetch);await api('/resumes');expect(fetch).toHaveBeenCalledWith('/api/resumes',expect.objectContaining({credentials:'include'}))});
});
