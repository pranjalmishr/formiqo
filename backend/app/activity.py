"""Actual owned activity and honest single-instance per-IP usage counters."""
import time
from fastapi import APIRouter,Depends,Request
from .persistence import find, resume_children
from sqlalchemy.orm import Session as DBSession
from .db import get_db,Resume,Analysis,EditorVersion,ConversionJob,now
from .storage import owner,_rates,_lock
from .config import settings

router=APIRouter(prefix='/api',tags=['Workspace activity'])


@router.get('/activity')
def activity(owner_id=Depends(owner),db:DBSession=Depends(get_db)):
    items=[]
    rows=resume_children(db,Analysis,owner_id,limit=10)
    for row,resume in rows: items.append({'id':row.id,'label':'Resume analyzed','detail':resume.filename+' · '+str(row.overall_score)+'/100 estimated','at':row.created_at.isoformat(),'url':'/app/results/'+row.id})
    rows=resume_children(db,EditorVersion,owner_id,limit=10)
    for row,resume in rows: items.append({'id':row.id,'label':'Resume draft saved','detail':resume.filename+' · '+row.change_summary,'at':row.created_at.isoformat(),'url':'/app/editor?resume='+resume.id})
    rows=find(db,ConversionJob,[('owner','==',owner_id),('expires_at','>',now())],[('created_at','desc')],limit=10)
    for row in rows: items.append({'id':row.id,'label':'Document conversion · '+row.status,'detail':row.source_filename+' · '+row.source_format.upper()+' → '+row.target_format.upper(),'at':(row.completed_at or row.created_at).isoformat(),'url':'/app/converter?job='+row.id})
    items.sort(key=lambda row:row['at'],reverse=True)
    return {'items':items[:15]}


@router.get('/usage')
def usage(request:Request,owner_id=Depends(owner)):
    address=request.client.host if request.client else 'unknown';tick=time.monotonic();buckets={}
    with _lock:
        for bucket in ['uploads','analyses','conversions','ai-writing','assistant']:
            timestamps=[t for t in _rates.get((address,bucket),[]) if t>tick-3600]
            buckets[bucket]={'used':len(timestamps),'limit':settings.guest_limit_per_hour,'remaining':max(0,settings.guest_limit_per_hour-len(timestamps)),'reset_in_seconds':max(0,int(3600-(tick-timestamps[0]))) if timestamps else 0}
    return {'buckets':buckets,'scope':'This API instance and IP address; shared networks share limits. Counters reset when the instance restarts.'}
