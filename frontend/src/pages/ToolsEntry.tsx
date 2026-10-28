import {useEffect,useState} from 'react';
import {Link,Navigate,useSearchParams} from 'react-router-dom';
import DocumentTools from './DocumentTools';
import {api} from '../lib/api';
import type {ConversionJob} from '../lib/converter';
import {Button} from '../components/ui/button';
// Preserve old bookmarked result URLs while making discovery the primary entry.
export default function ToolsEntry(){const[params]=useSearchParams();const job=params.get('job');const[target,setTarget]=useState(''),[error,setError]=useState('');useEffect(()=>{let active=true;setTarget('');setError('');if(job)api<ConversionJob>('/converter/jobs/'+job).then(value=>{if(active)setTarget((value.settings._tool_id?'/app/tools/'+value.settings._tool_id:'/app/converter/legacy')+'?job='+value.id)}).catch(err=>active&&setError(err.message));return()=>{active=false}},[job]);if(!job)return <DocumentTools/>;if(target)return <Navigate to={target} replace/>;if(error)return <div role="alert" className="notice error">{error}<Button asChild variant="outline" className="ml-3"><Link to="/app/converter">Return to tools</Link></Button></div>;return <p role="status" className="studio-status">Opening the authorized document workspace…</p>}
