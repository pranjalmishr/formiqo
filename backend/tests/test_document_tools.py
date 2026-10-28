import io
import json
from pathlib import Path
import pytest
import pymupdf
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app.document_tools import TOOLS,ToolSettings,operate,inspect_inputs
from app.conversion import ConversionError,matrix
from app.converter_api import job_dir


def pdf_bytes():
 doc=pymupdf.open()
 for index in range(3):doc.new_page().insert_text((45,50),'ACTUAL PAGE '+str(index+1)+'\nVerified source content.')
 return doc.tobytes()


@pytest.mark.parametrize('operation',[key for key in TOOLS if key.startswith('pdf-')])
def test_real_pdf_operations(tmp_path,operation):
 a=tmp_path/'a.pdf';b=tmp_path/'b.pdf';a.write_bytes(pdf_bytes());b.write_bytes(pdf_bytes());out=tmp_path/'out';out.mkdir()
 settings=ToolSettings(pages='2',page_order=[3,1,2],file_order=[1,0],degrees=90,watermark='REVIEWED')
 result=operate([a,b] if operation=='pdf-merge' else [a],['pdf','pdf'] if operation=='pdf-merge' else ['pdf'],operation,out,settings)
 assert result['outputs']
 for output in result['outputs']:
  assert (out/output['filename']).stat().st_size==output['size']
  if output['format']=='pdf':
   with pymupdf.open(out/output['filename']) as doc:
    if operation=='pdf-merge':assert len(doc)==6
    if operation in ('pdf-extract','pdf-split'):assert len(doc)==1 and 'PAGE 2' in doc[0].get_text()
    if operation=='pdf-delete':assert len(doc)==2 and all('PAGE 2' not in p.get_text() for p in doc)
    if operation=='pdf-reorder':assert 'PAGE 3' in doc[0].get_text()
    if operation=='pdf-rotate':assert doc[1].rotation==90 and doc[0].rotation==0
    if operation=='pdf-watermark':assert 'REVIEWED' in doc[0].get_text()
    if operation=='pdf-numbers':assert '1 / 3' in doc[0].get_text()


@pytest.mark.parametrize('operation',['image-resize','image-crop','image-rotate','image-compress'])
def test_real_image_operations(tmp_path,operation):
 source=tmp_path/'source.jpg';Image.new('RGB',(400,200),'navy').save(source);out=tmp_path/'out';out.mkdir()
 result=operate([source],['jpg'],operation,out,ToolSettings(width=100,height=100,x=10,y=10,crop_width=80,crop_height=50,degrees=90))
 with Image.open(out/result['outputs'][0]['filename']) as image:
  if operation=='image-resize':assert image.size==(100,50)
  if operation=='image-crop':assert image.size==(80,50)
  if operation=='image-rotate':assert image.size==(200,400)


def test_prepare_preview_run_ownership_and_cancel(client):
 result=client.post('/api/tools/prepare',files={'files':('actual.pdf',pdf_bytes(),'application/pdf')},data={'tool':'pdf-reorder'})
 assert result.status_code==202,result.text
 rid=result.json()['id'];job=client.get('/api/converter/jobs/'+rid).json();assert job['status']=='prepared',job
 assert job['settings']['_inspection'][0]['pages']==3
 assert (job_dir(rid)/'inputs').exists()
 assert client.get('/api/tools/'+rid+'/thumbnail?page=1').status_code==200
 with TestClient(app) as other:
  other.get('/api/config');assert other.get('/api/tools/'+rid+'/thumbnail').status_code==404
  assert other.post('/api/tools/'+rid+'/run',json={'settings':{}}).status_code==404
 result=client.post('/api/tools/'+rid+'/run',json={'settings':{'page_order':[3,1,2]}})
 assert result.status_code==202,result.text
 job=client.get('/api/converter/jobs/'+rid).json();assert job['status']=='completed',job
 data=client.get('/api/converter/jobs/'+rid+'/download').content
 with pymupdf.open(stream=data,filetype='pdf') as doc:assert 'PAGE 3' in doc[0].get_text()
 assert not (job_dir(rid)/'inputs').exists()
 assert client.post('/api/tools/'+rid+'/run',json={'settings':{}}).status_code==409
 assert client.delete('/api/converter/jobs/'+rid).status_code==204
 assert not job_dir(rid).exists()


def test_invalid_crop_order_and_unavailable_word_renderer(client,tmp_path):
 source=tmp_path/'source.png';Image.new('RGB',(100,80),'white').save(source);out=tmp_path/'out';out.mkdir()
 with pytest.raises(ConversionError,match='within'):operate([source],['png'],'image-crop',out,ToolSettings(x=90,crop_width=50))
 source=tmp_path/'source.pdf';source.write_bytes(pdf_bytes())
 with pytest.raises(ConversionError,match='each page once'):operate([source],['pdf'],'pdf-reorder',out,ToolSettings(page_order=[1,1,2]))
 catalog=client.get('/api/tools/catalog').json()['items']
 word=next(item for item in catalog if item['id']=='convert-docx-pdf')
 assert not word['available'] and 'pdf' not in matrix()['docx']
 assert client.post('/api/tools/prepare',files={'files':('test.pdf',pdf_bytes(),'application/pdf')},data={'tool':'nonexistent'}).status_code==415
