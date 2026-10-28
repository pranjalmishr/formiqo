import {useEffect,useMemo,useRef,useState} from 'react';
import type {ResumeSection} from '../lib/editor';
import type {Template} from '../lib/builder';
import {DocumentCanvas} from './DocumentCanvas';
// Guided intake and matcher previews share the actual studio/PDF document engine.
export function ResumePreview({sections,template,compact=false}:{sections:ResumeSection[];template?:Template;compact?:boolean}){
 const host=useRef<HTMLDivElement>(null);const[zoom,setZoom]=useState(compact ? .32 : .5);
 const content=useMemo(()=>({sections,template:template?.id||'classic-ats',style:{page_size:'A4' as const}}),[sections,template?.id]);
 useEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(entries=>setZoom(Math.max(.2,Math.min(1,(entries[0].contentRect.width-12)/794))));observer.observe(host.current);return()=>observer.disconnect()},[]);
 // An empty draft has no sections yet; the studio API requires at least one, so wait for content.
 return <div ref={host} className="resume-preview-host">{sections.length?<DocumentCanvas content={content} zoom={zoom}/>:null}</div>;
}
