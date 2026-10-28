import {describe,it,expect} from 'vitest';
import {fileFormat,validateConversionFiles,fileSize,type ConversionCapabilities} from './converter';
const cap:ConversionCapabilities={matrix:{txt:['pdf','docx'],png:['pdf','jpg'],jpg:['pdf','png']},max_upload_mb:1,max_files:10,max_pages:30,ocr_available:false,office_available:false,dpi_presets:[72,150,200],warnings:[]};
describe('capability-driven conversion validation',()=>{
 it('normalizes JPEG without treating DOC as DOCX',()=>{expect(fileFormat(new File(['x'],'photo.JPEG'))).toBe('jpg');expect(validateConversionFiles([new File(['x'],'legacy.doc')],cap)).toMatch(/Legacy DOC/)});
 it('accepts ordered mixed images but not arbitrary batches',()=>{expect(validateConversionFiles([new File(['a'],'one.png'),new File(['b'],'two.jpg')],cap)).toBeNull();expect(validateConversionFiles([new File(['a'],'one.txt'),new File(['b'],'two.png')],cap)).toMatch(/Multiple uploads/)});
 it('rejects empty and oversized data before upload',()=>{expect(validateConversionFiles([new File([],'empty.txt')],cap)).toMatch(/empty/);expect(validateConversionFiles([new File([new Uint8Array(1024*1024+1)],'large.txt')],cap)).toMatch(/smaller/)});
 it('formats actual byte counts',()=>{expect(fileSize(100)).toBe('100 B');expect(fileSize(2048)).toBe('2.0 KB');expect(fileSize(1024*1024)).toBe('1.0 MB')});
});
