"""Real PDF/image operations; each tool has a constrained input/settings contract."""
from pathlib import Path
import zipfile
from typing import Literal
from pydantic import BaseModel,Field
import pymupdf
from PIL import ImageOps
from .conversion import open_pdf,image,rgb,validate_output,ConversionError,MIMES,page_indices

TOOLS={
 'pdf-merge':{'name':'Merge PDFs','category':'PDF editing','description':'Combine ordered documents into one PDF.','sources':['pdf'],'target':'pdf','multiple':True},
 'pdf-split':{'name':'Split PDF','category':'PDF editing','description':'Save selected pages as individual PDFs, plus a ZIP.','sources':['pdf'],'target':'pdf'},
 'pdf-compress':{'name':'Compress PDF','category':'PDF editing','description':'Lossless object cleanup and stream compression. Reduction is not guaranteed.','sources':['pdf'],'target':'pdf'},
 'pdf-rotate':{'name':'Rotate PDF pages','category':'PDF editing','description':'Rotate selected pages in right-angle increments.','sources':['pdf'],'target':'pdf'},
 'pdf-reorder':{'name':'Reorder PDF pages','category':'PDF editing','description':'Arrange every page in your chosen order.','sources':['pdf'],'target':'pdf'},
 'pdf-extract':{'name':'Extract PDF pages','category':'PDF editing','description':'Create one PDF from a selected page range.','sources':['pdf'],'target':'pdf'},
 'pdf-delete':{'name':'Delete PDF pages','category':'PDF editing','description':'Remove selected pages while keeping at least one page.','sources':['pdf'],'target':'pdf'},
 'pdf-numbers':{'name':'Add page numbers','category':'PDF editing','description':'Add visible page counts at the bottom of each page.','sources':['pdf'],'target':'pdf'},
 'pdf-watermark':{'name':'Add a watermark','category':'PDF editing','description':'Place a restrained text watermark on each page.','sources':['pdf'],'target':'pdf'},
 'image-resize':{'name':'Resize image','category':'Image editing','description':'Fit within a pixel box, preserving aspect ratio.','sources':['jpg','png','webp'],'target':'source'},
 'image-crop':{'name':'Crop image','category':'Image editing','description':'Crop a precise rectangle without padding or stretching.','sources':['jpg','png','webp'],'target':'source'},
 'image-rotate':{'name':'Rotate image','category':'Image editing','description':'Rotate without clipping the image.','sources':['jpg','png','webp'],'target':'source'},
 'image-compress':{'name':'Compress image','category':'Image editing','description':'Adjust JPEG/WEBP quality or optimize PNG losslessly.','sources':['jpg','png','webp'],'target':'source'},
}


class ToolSettings(BaseModel):
 model_config={'extra':'forbid'}
 pages:str=Field(default='',max_length=150)
 page_order:list[int]=Field(default_factory=list,max_length=50)
 file_order:list[int]=Field(default_factory=list,max_length=10)
 degrees:Literal[90,180,270]=90
 width:int=Field(default=1200,ge=1,le=6000)
 height:int=Field(default=1200,ge=1,le=6000)
 x:int=Field(default=0,ge=0,le=20000)
 y:int=Field(default=0,ge=0,le=20000)
 crop_width:int=Field(default=100,ge=1,le=20000)
 crop_height:int=Field(default=100,ge=1,le=20000)
 quality:int=Field(default=80,ge=10,le=95)
 watermark:str=Field(default='DRAFT',min_length=1,max_length=100)


def inspect_inputs(paths,formats):
 result=[]
 for path,fmt in zip(paths,formats):
  if fmt=='pdf':
   with open_pdf(path) as doc:result.append({'format':fmt,'pages':len(doc),'width_pt':round(doc[0].rect.width,1),'height_pt':round(doc[0].rect.height,1)})
  elif fmt in ('jpg','png','webp'):
   img=image(path);result.append({'format':fmt,'width':img.width,'height':img.height,'pages':1});img.close()
  else:
   from .conversion import safe_text,docx_html
   from .editor_content import plain_text
   text=plain_text(docx_html(path)) if fmt=='docx' else safe_text(path) if fmt in ('txt','html') else ''
   result.append({'format':fmt,'pages':None,'characters':len(text),'text_preview':text[:1500]})
 return result


def thumbnail(path,fmt,output,page=1):
 if fmt=='pdf':
  with open_pdf(path) as doc:
   if not 1<=page<=len(doc):raise ConversionError('Preview page is outside this document.','invalid_page_range')
   p=doc[page-1];scale=min(300/p.rect.width,420/p.rect.height);p.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).save(output)
 else:
  img=image(path);img.thumbnail((300,420));img.save(output,format='PNG');img.close()
 validate_output(output,'png')
 return {'filename':output.name}


def operate(paths,formats,operation,work,options:ToolSettings):
 if operation not in TOOLS:raise ConversionError('Unknown document operation.','unsupported_operation')
 tool=TOOLS[operation];warnings=[];outputs=[]
 if any(fmt not in tool['sources'] for fmt in formats):raise ConversionError('A file format is not accepted by this tool.','invalid_file')
 if not tool.get('multiple') and len(paths)!=1:raise ConversionError('Choose one input for this tool.','unsupported_batch')
 if operation.startswith('pdf-'):
  output=work/'edited.pdf'
  if operation=='pdf-merge':
   order=options.file_order or list(range(len(paths)))
   if sorted(order)!=list(range(len(paths))):raise ConversionError('Document order must contain every uploaded file once.','invalid_order')
   out=pymupdf.open()
   for index in order:
    with open_pdf(paths[index]) as doc:out.insert_pdf(doc)
   if len(out)>50:raise ConversionError('Merged PDF exceeds 50 pages.','page_limit')
  else:
   doc=open_pdf(paths[0]);selected=page_indices(options.pages,len(doc))
   if operation=='pdf-split':
    for index in selected:
     out=pymupdf.open();out.insert_pdf(doc,from_page=index,to_page=index);part=work/f'page-{index+1:03d}.pdf';out.save(part);out.close();outputs.append(part)
    archive=work/'split-pages.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
     for part in outputs:z.write(part,part.name)
    outputs.append(archive);doc.close();out=None
   elif operation=='pdf-extract':
    out=pymupdf.open()
    for index in selected:out.insert_pdf(doc,from_page=index,to_page=index)
    doc.close()
   elif operation=='pdf-delete':
    if len(selected)>=len(doc):doc.close();raise ConversionError('Keep at least one page.','empty_document')
    out=doc;out.delete_pages(selected)
   elif operation=='pdf-reorder':
    order=options.page_order or list(range(1,len(doc)+1))
    if sorted(order)!=list(range(1,len(doc)+1)):doc.close();raise ConversionError('Page order must contain each page once.','invalid_order')
    out=pymupdf.open()
    for index in order:out.insert_pdf(doc,from_page=index-1,to_page=index-1)
    doc.close()
   else:
    out=doc
    if operation=='pdf-rotate':
     for index in selected:out[index].set_rotation((out[index].rotation+options.degrees)%360)
    elif operation=='pdf-watermark':
     if any(ord(c)>255 or ord(c)<32 for c in options.watermark):doc.close();raise ConversionError('Watermark currently supports printable Latin text only.','unsupported_text')
     for p in out:
      width=pymupdf.get_text_length(options.watermark,fontsize=24);p.insert_text((max(12,(p.rect.width-width)/2),p.rect.height/2),options.watermark,fontsize=24,color=(.4,.4,.4),fill_opacity=.2,overlay=True)
    elif operation=='pdf-numbers':
     for index,p in enumerate(out):p.insert_text((p.rect.width/2-12,p.rect.height-18),f'{index+1} / {len(out)}',fontsize=9,color=(.35,.35,.35))
    elif operation=='pdf-compress':warnings.append('Lossless cleanup only; image quality is unchanged and file size may not decrease.')
  if out is not None:
   out.save(output,garbage=4,deflate=True,clean=True);out.close();outputs=[output]
   if operation=='pdf-compress' and output.stat().st_size>=paths[0].stat().st_size:warnings.append('This input did not become smaller. The original has not been overwritten.')
 else:
  fmt=formats[0];img=image(paths[0]);output=work/('edited.'+fmt)
  if operation=='image-resize':img=ImageOps.contain(img,(options.width,options.height))
  elif operation=='image-crop':
   if options.x+options.crop_width>img.width or options.y+options.crop_height>img.height:img.close();raise ConversionError('Crop rectangle must stay within the image dimensions.','invalid_crop')
   img=img.crop((options.x,options.y,options.x+options.crop_width,options.y+options.crop_height))
  elif operation=='image-rotate':img=img.rotate(-options.degrees,expand=True)
  if fmt in ('jpg','webp'):img=rgb(img)
  img.save(output,format={'jpg':'JPEG','png':'PNG','webp':'WEBP'}[fmt],quality=options.quality,optimize=True);img.close();outputs=[output]
  if operation=='image-compress' and output.stat().st_size>=paths[0].stat().st_size:warnings.append('The optimized output is not smaller. Size reduction is not guaranteed; original quality/content may already be efficient.')
 result=[]
 for path in outputs:
  ext=path.suffix.lstrip('.');validate_output(path,ext);item={'filename':path.name,'format':ext,'size':path.stat().st_size,'mime':MIMES[ext]}
  if ext=='pdf':
   with pymupdf.open(path) as doc:item['pages']=len(doc)
  elif ext!='zip':
   from PIL import Image
   with Image.open(path) as img:item.update(width=img.width,height=img.height)
  result.append(item)
 return {'outputs':result,'warnings':warnings}
