import { z } from 'zod';
import type { ResumeSection } from './editor';
const short = z.string().max(180).regex(/^[^\r\n\t]*$/, 'Use a single line for this field.');
const long = z.string().max(12000);
const date = z.string().regex(/^(?:|\d{4}(?:-(?:0[1-9]|1[0-2]))?)$/, 'Use YYYY or YYYY-MM, or leave blank.');
const url = short.refine(value => { if(!value)return true;try{const link=new URL(value);return ['http:','https:'].includes(link.protocol)&&!!link.hostname&&!link.username&&!/\s/.test(value)}catch{return false} }, 'Use a full http:// or https:// URL.');
const dated = { start:date, end:date, current:z.boolean() };
export const orderKeys=['summary','experience','education','skills','projects','certifications','achievements','additional'] as const;
export const orderLabels:Record<string,string>={summary:'Professional Summary',experience:'Experience',education:'Education',skills:'Technical Skills',projects:'Projects',certifications:'Certifications',achievements:'Achievements',additional:'Additional sections'};
export const builderSchema=z.object({
 contact:z.object({name:short,email:short.refine(value=>!value||/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value),'Enter a valid email address.'),phone:short,location:short,website:url,linkedin:url}),
 target_role:short, summary:long,
 experience:z.array(z.object({title:short,employer:short,location:short,highlights:long,...dated})).max(15),
 education:z.array(z.object({institution:short,qualification:short,details:long,...dated})).max(10),
 skills:z.string().max(6000),
 projects:z.array(z.object({name:short,url,technologies:short,highlights:long})).max(15),
 certifications:z.array(z.object({name:short,issuer:short,date,url})).max(15),
 achievements:long,
 additional:z.array(z.object({title:z.string().max(100).regex(/^[^\r\n\t]*$/, 'Use a single-line section title.'),content:long})).max(10),
 template:z.enum(['classic-ats','traditional-corporate','clean-executive','modern-professional','minimalist','elegant-typography','technical','machine-learning','data-scientist','engineering','student','fresher','internship','experienced','executive-leadership','two-column','sidebar-skills','contemporary-creative']),
 section_order:z.array(z.string()).length(8).refine(value=>new Set(value).size===8&&value.every(key=>orderKeys.includes(key as typeof orderKeys[number])),'Include every section exactly once.'),
 step:z.number().int().min(1).max(10),
}).superRefine((data,ctx)=>{
 for(const key of ['experience','education'] as const) data[key].forEach((entry,index)=>{
  if(entry.current&&entry.end)ctx.addIssue({code:'custom',path:[key,index,'end'],message:'Clear the end date for a current entry.'});
  if(entry.start&&entry.end&&(entry.end.slice(0,4)<entry.start.slice(0,4)||(entry.start.length===7&&entry.end.length===7&&entry.end<entry.start)))ctx.addIssue({code:'custom',path:[key,index,'end'],message:'End date cannot precede the start date.'});
 });
});
export type BuilderData=z.infer<typeof builderSchema>;
export interface Template {id:BuilderData['template'];name:string;description:string;font:'serif'|'sans';body_size:number;heading_size:number;leading:number;spacing:number;margin:number;accent:string}
export interface BuilderDraft {resume_id:string;filename:string;revision:number;data:BuilderData;content:{sections:ResumeSection[];template:BuilderData['template']};out_of_sync:boolean;export_issues:string[];updated_at:string;expires_at:string}
export const emptyBuilder:BuilderData={contact:{name:'',email:'',phone:'',location:'',website:'',linkedin:''},target_role:'',summary:'',experience:[],education:[],skills:'',projects:[],certifications:[],achievements:'',additional:[],template:'classic-ats',section_order:[...orderKeys],step:1};
export const steps=[{title:'Contact information',short:'Contact',description:'How can someone reach you? Add only the contact details you want to share.'},{title:'Your direction & summary',short:'Summary',description:'Give your story a focus. Describe your actual strengths, not an imaginary next version of you.'},{title:'Work experience',short:'Experience',description:'Your real roles and contributions. New to work? Skip this step and let projects or education tell your story.'},{title:'Education',short:'Education',description:'Include the education or training relevant to your next step. A degree is not required.'},{title:'Your skills',short:'Skills',description:'List tools, methods and strengths you can genuinely use. No keyword stuffing needed.'},{title:'Projects',short:'Projects',description:'Show what you have built, researched or contributed to. Personal and academic work count.'},{title:'Certifications & achievements',short:'Achievements',description:'Add verified credentials and real accomplishments. Leave anything that does not apply blank.'},{title:'The rest of your story',short:'Additional',description:'Languages, volunteering, publications or something unique. Add relevant sections, then choose their order.'},{title:'Choose your presentation',short:'Template',description:'Eighteen real layouts, from single-column ATS classics to sidebars. The content stays yours; only its presentation changes.'},{title:'Ready for your next chapter.',short:'Review & export',description:'Review your saved resume, verify the facts and download a real PDF or Word document.'}];
export function hasBuilderContent(data:BuilderData){return !!(data.contact.name.trim()||data.summary.trim()||data.experience.length||data.education.length||data.skills.trim()||data.projects.length||data.certifications.length||data.achievements.trim()||data.additional.length)}
export async function builderExport(id:string,format:'pdf'|'docx') {
 const response=await fetch(`/api/builder/${id}/export?format=${format}`,{method:'POST',credentials:'include'});
 if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.detail||'Export failed. Please retry.');}
 const blob=await response.blob();if(!blob.size)throw new Error('The generated export is empty.');return blob;
}
