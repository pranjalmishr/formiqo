import {useMemo,useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight,CheckCircle2,CircleDashed,ListChecks} from 'lucide-react';
import type {Analysis,KeywordTerm} from '../lib/api';

/* Weighted job-term coverage (rubric v2). Missing terms are visibility gaps to confirm,
   never assumed missing skills; confirmation never edits the resume. */
const GROUPS:{key:NonNullable<KeywordTerm['importance']>;label:string;hint:string}[]=[
 {key:'required',label:'Required',hint:'Named in requirements or qualifications · weight 3'},
 {key:'core',label:'Core responsibilities',hint:'Named in what the role does · weight 2'},
 {key:'mentioned',label:'Mentioned',hint:'Named elsewhere in the description · weight 1.5'},
 {key:'preferred',label:'Preferred',hint:'Nice-to-have or bonus · weight 1'},
];
type Filter='all'|'missing'|'present';

export function termsOf(report:Analysis):KeywordTerm[]{
 const k=report.keywords;
 if(k.contexts?.length)return k.contexts;
 // Older (rubric 1.x) analyses: show found/missing without weights.
 return [...k.found.map(term=>({term,present:true,kind:'candidate term',contexts:[],requires_confirmation:false})),...k.missing.map(term=>({term,present:false,kind:'candidate term',contexts:[],requires_confirmation:true}))];
}

export function KeywordCoverage({report,editLink}:{report:Analysis;editLink:string}){
 const[filter,setFilter]=useState<Filter>('all');const[confirmed,setConfirmed]=useState<string[]>([]);
 const terms=useMemo(()=>termsOf(report),[report]);const k=report.keywords;
 const weighted=typeof k.weighted_coverage==='number'?Math.round(k.weighted_coverage*100):null;
 const evidence=typeof k.evidence_coverage==='number'?Math.round(k.evidence_coverage*100):null;
 const visible=terms.filter(term=>filter==='all'||(filter==='missing'?!term.present:term.present));
 const grouped=GROUPS.map(group=>({...group,items:visible.filter(term=>(term.importance||'mentioned')===group.key)})).filter(group=>group.items.length);
 return <div className="keyword-coverage">
  <section className="coverage-summary" aria-label="Job term coverage summary">
   <div className="coverage-meter"><span>Weighted coverage</span><strong>{weighted??Math.round(100*k.found.length/Math.max(1,k.candidate_count))}<small>%</small></strong><i aria-hidden="true"><b style={{width:(weighted??Math.round(100*k.found.length/Math.max(1,k.candidate_count)))+'%'}}/></i><p>{weighted!==null?'Share of term importance explicitly visible in your resume.':'Share of candidate terms found (older analysis without weights).'}</p></div>
   <div className="coverage-facts">
    <div><ListChecks size={16}/><span><strong>{k.required_total!==undefined?`${k.required_found} / ${k.required_total}`:'—'}</strong>required terms visible</span></div>
    <div><CheckCircle2 size={16}/><span><strong>{k.found.length} / {k.candidate_count}</strong>terms represented</span></div>
    <div><CircleDashed size={16}/><span><strong>{evidence!==null?evidence+'%':'—'}</strong>of matched weight shown in experience or projects</span></div>
   </div>
  </section>
  {!!k.missing_required?.length&&<p className="coverage-callout"><strong>Confirm first:</strong> {k.missing_required.join(', ')}. These come from the requirements. A missing word is a visibility gap, not proof you lack the skill.</p>}
  <div className="coverage-toolbar"><h2>Job terms in their actual context</h2><div className="text-view-switch" role="group" aria-label="Filter job terms">{([['all','All'],['missing','To confirm'],['present','Represented']] as [Filter,string][]).map(([key,label])=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{label} ({key==='all'?terms.length:terms.filter(term=>key==='missing'?!term.present:term.present).length})</button>)}</div></div>
  <p className="analysis-context-note">{k.method} Never stuff keywords; add a term only where it describes verified experience.</p>
  {grouped.map(group=><section key={group.key} className="term-group" aria-label={group.label+' terms'}><header><h3>{group.label}</h3><span>{group.hint}</span></header><div className="keyword-context-list">{group.items.map(term=><article key={term.term} className={term.present?'term-present':'term-missing'}>
   <div><strong>{term.term}</strong><span className={term.present?'found-term':'missing-term'}>{term.present?'Explicitly represented':'Not clearly represented'}</span>{term.present&&term.matched_as&&term.matched_as!==term.term&&<span className="term-alias">matched as “{term.matched_as}”</span>}<small>{term.kind}{term.weight!==undefined?' · weight '+term.weight:''}</small></div>
   {term.present&&term.where&&<p className="term-where">Found in: {term.where.join(', ')}{term.where.length===1&&term.where[0]==='skills'?'. Consider showing where you used it in an experience or project bullet.':''}</p>}
   {term.contexts.map((context,index)=><blockquote key={index}><span>{context.group}</span>{context.excerpt}</blockquote>)}
   {!term.present&&<label className="check-control"><input type="checkbox" checked={confirmed.includes(term.term)} onChange={event=>setConfirmed(values=>event.target.checked?[...values,term.term]:values.filter(value=>value!==term.term))}/>I have relevant experience with this term. Confirmation does not automatically add it to my resume.</label>}
   {confirmed.includes(term.term)&&<Link className="keyword-review-link" to={editLink+'&panel=ai'}>Review how to express verified experience <ArrowRight size={13}/></Link>}
  </article>)}</div></section>)}
  {!grouped.length&&<p className="analysis-context-note">No terms match this filter.</p>}
 </div>;
}
