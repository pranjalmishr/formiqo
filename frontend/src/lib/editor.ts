import { api } from './api';
export interface ResumeSection { id: string; title: string; html: string }
export interface EditorDraft {
  resume_id: string; filename: string; revision: number;
  content: { sections: ResumeSection[]; template?: string }; applied: string[]; rejected: string[];
  updated_at: string; expires_at: string; out_of_sync: boolean; original_text: string;
}
export interface EditorVersion { id: string; revision: number; content: EditorDraft['content']; change_summary: string; created_at: string }
export interface Suggestion { id: string; original: string; suggested: string; notes: string[]; requires_confirmation: boolean; notice: string }
export const writingActions = ['Improve wording', 'Make it more professional', 'Make it more concise', 'Fix grammar', 'Achievement-oriented bullets', 'Improve clarity', 'Suggest measurable impact', 'ATS readability', 'Align with job description', 'Generate summary', 'Improve skills presentation', 'Stronger action verbs'] as const;
export const sectionNames = ['Contact information', 'Professional Summary', 'Experience', 'Education', 'Technical Skills', 'Projects', 'Certifications', 'Achievements', 'Publications', 'Languages', 'Volunteer Experience', 'Custom section'];
export function htmlText(html: string): string {
  const body = new DOMParser().parseFromString(html, 'text/html').body;
  function visit(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
    const element = node as HTMLElement;
    const content = Array.from(node.childNodes).map(visit).join('');
    if (element.tagName === 'BR') return '\n';
    if (element.tagName === 'LI') return '\n• ' + content.trim() + '\n';
    if (['P','H2','H3'].includes(element.tagName)) return '\n' + content + '\n';
    return content;
  }
  return visit(body).replace(/\n{3,}/g, '\n\n').trim();
}
export function escapeHTML(text: string) { return text.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!)); }
export function textHTML(text: string) {
  let html = '', list = false;
  for (const line of text.split('\n').filter(line => line.trim())) {
    const bullet = /^\s*[-•]\s+/.test(line);
    if (bullet && !list) { html += '<ul>'; list = true; }
    if (!bullet && list) { html += '</ul>'; list = false; }
    const value = escapeHTML(line.replace(/^\s*[-•]\s+/,''));
    html += bullet ? `<li><p>${value}</p></li>` : `<p>${value}</p>`;
  }
  return html + (list ? '</ul>' : '') || '<p></p>';
}
export function draftText(sections: ResumeSection[]) {
  return sections.map(section => (section.title.toLowerCase() === 'contact information' ? '' : section.title + '\n') + htmlText(section.html)).join('\n\n').trim();
}
export function snapshot(sections: ResumeSection[], applied: string[], rejected: string[]) { return JSON.stringify({content:{sections},applied,rejected}); }
export async function exportBlob(id: string, format: 'pdf'|'docx') {
  const response = await fetch(`/api/editor/${id}/export?format=${format}`, {credentials:'include'});
  if (!response.ok) {const error=await response.json().catch(()=>({}));throw new Error(error.detail || 'Export failed. Please retry.');}
  const blob = await response.blob();
  if (!blob.size) throw new Error('The server returned an empty export.');
  return blob;
}
export async function saveDraft(draft: EditorDraft, sections: ResumeSection[], applied: string[], rejected: string[], summary: string) {
  return api<EditorDraft>('/editor/'+draft.resume_id, {method:'PATCH',body:JSON.stringify({revision:draft.revision,content:{...draft.content,sections},applied,rejected,change_summary:summary})});
}
