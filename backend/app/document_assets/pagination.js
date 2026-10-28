/* Canonical canvas pagination. The same DOM runs in preview and Chromium PDF export. */
(async function(){
 const cfg=JSON.parse(document.getElementById('document-data').textContent),root=document.querySelector('.document-pages');
 const sections=cfg.content.sections,def=cfg.definition,warnings=[],dirtySections=new Set();
 const send=(kind,data={})=>{if(window.parent!==window)window.parent.postMessage({type:'formiqo:document',token:cfg.token,kind,...data},'*')};
 try{const family={sans:'StudioSans',serif:'StudioSerif',mono:'StudioMono'}[def.font];const families=[...new Set([family,'StudioSans',...(def.header==='code'?['StudioMono']:[])])];await Promise.all(families.flatMap(name=>[document.fonts.load('400 12pt '+name),document.fonts.load('700 12pt '+name)]));await document.fonts.ready}catch(error){window.__FORMIQO_ERROR__='Document fonts could not be loaded. Retry after checking the server connection.';send('error',{message:window.__FORMIQO_ERROR__});return}
 const contact=sections.find(s=>s.title.toLowerCase()==='contact information');
 const sectionKind=s=>{const t=s.title.toLowerCase();return ['skills','education','certifications','projects','summary','languages','experience'].find(k=>t.includes(k))||'custom'};
 const blocksOf=s=>{const div=document.createElement('div');div.innerHTML=s.html;const items=[],normalized=[];let inline=null;const flush=()=>{if(inline){normalized.push(inline);inline=null}};for(const child of Array.from(div.childNodes)){if(child.nodeType===Node.ELEMENT_NODE&&['P','UL','OL','H2','H3'].includes(child.tagName)){flush();normalized.push(child.cloneNode(true))}else if(child.textContent.trim()||child.nodeName==='BR'){if(!inline)inline=document.createElement('p');inline.appendChild(child.cloneNode(true))}}flush();for(const child of normalized){
   if(['UL','OL'].includes(child.tagName)){for(const li of Array.from(child.children)){const list=document.createElement(child.tagName);list.appendChild(li.cloneNode(true));items.push(list)}}else items.push(child.cloneNode(true));
  }if(!items.length){const p=document.createElement('p');p.textContent=div.textContent;items.push(p)}
  return items.map((child,index)=>{const node=document.createElement('div');node.className='doc-block'+(s===contact?' contact-block':'');node.dataset.section=s.id;node.dataset.block=String(index);node.dataset.kind=sectionKind(s);node.appendChild(child);if(cfg.interactive){node.contentEditable='true';node.setAttribute('role','textbox');node.setAttribute('aria-label',s.title+' passage '+(index+1));node.dataset.placeholder='Click to add your text'}
   if(s!==contact&&cfg.style.date_alignment==='right'&&/\b(?:19|20)\d{2}\b/.test(node.textContent)&&node.textContent.length<110&&!node.querySelector('strong'))node.classList.add('date-right');
   if(sectionKind(s)==='skills'&&def.skills!=='text'&&child.tagName==='P'&&!child.querySelector('a')&&child.textContent.includes(',')){const terms=child.textContent.split(',');child.textContent='';terms.forEach((term,i)=>{const span=document.createElement('span');span.className='skill-term';span.textContent=term.trim()+(i<terms.length-1?', ':'');child.appendChild(span)});node.replaceChildren(child)}
   for(const anchor of node.querySelectorAll('a')){if(anchor.childNodes.length===1&&anchor.firstChild.nodeType===Node.TEXT_NODE){const value=anchor.textContent;anchor.textContent='';for(const token of value.split(/([/@._-])/)){anchor.appendChild(document.createTextNode(token));if(/^[/@._-]$/.test(token))anchor.appendChild(document.createElement('wbr'))}}}
   return node});
 };
 const allBlocks=new Map(sections.map(s=>[s.id,blocksOf(s)]));
 const isRail=s=>s.placement==='rail'||s.placement!=='main'&&def.rail.some(k=>sectionKind(s)===k);
 const two=def.columns===2;
 const main=sections.filter(s=>s!==contact&&(!def.lead.includes(sectionKind(s))||s.page_break_before)&&(!two||!isRail(s)));
 const rail=two?sections.filter(s=>s!==contact&&(!def.lead.includes(sectionKind(s))||s.page_break_before)&&isRail(s)):[];
 const lead=sections.filter(s=>s!==contact&&def.lead.includes(sectionKind(s))&&!s.page_break_before);
 const titleOf=s=>{const node=document.createElement('h2');node.className='doc-section-title';node.dataset.sectionTitle=s.id;node.dataset.index=String(sections.indexOf(s)).padStart(2,'0');node.textContent=s.title;return node};
 const headerBlocks=contact?[...allBlocks.get(contact.id)]:[];
 const pages=[];
 function headerNode(){const header=document.createElement('header');header.className='resume-header header-'+def.header;
  const identity=document.createElement('div'),channels=document.createElement('div');identity.className='header-identity';channels.className='header-contact';
  headerBlocks.forEach((node,i)=>{const copy=node.cloneNode(true);if(i===1&&!/[@\d]|https?:/.test(copy.textContent))copy.classList.add('contact-role');(i<2?identity:channels).appendChild(copy)});
  if(def.header==='split'){header.append(identity,channels)}else header.append(...identity.children,...channels.children);return header;
 }
 function pageAt(index){while(pages.length<=index){if(pages.length>80)throw new Error('Document exceeds the 80-page rendering limit; shorten content or reduce manual breaks.');const number=pages.length,page=document.createElement('article');page.className='resume-page';page.dataset.page=String(number+1);page.setAttribute('aria-label','Resume page '+(number+1));const inner=document.createElement('div');inner.className='page-inner';page.appendChild(inner);root.appendChild(page);
   if(number===0&&def.header!=='rail'&&headerBlocks.length)inner.appendChild(headerNode());
   if(number>0&&headerBlocks.length){const label=document.createElement('div');label.className='continuation-label';label.textContent=headerBlocks[0].textContent;inner.appendChild(label)}
   const leadNode=document.createElement('div');leadNode.className='resume-lead';if(number===0){for(const s of lead){leadNode.appendChild(titleOf(s));allBlocks.get(s.id).forEach(block=>leadNode.appendChild(block.cloneNode(true)))}inner.appendChild(leadNode);if(leadNode.getBoundingClientRect().height>page.clientHeight*.4){leadNode.remove();if(!warnings.includes('Long lead sections flowed into the main document stream.')){warnings.push('Long lead sections flowed into the main document stream.');main.unshift(...lead)}}}
   const body=document.createElement('div');body.className='resume-body';if(two){const ratio=def.column_ratio;body.style.gridTemplateColumns=def.layout==='sidebar-left'?`${1-ratio}fr ${ratio}fr`:`${ratio}fr ${1-ratio}fr`}inner.appendChild(body);
   const lanes=[];const order=two?(def.layout==='sidebar-left'?['rail','main']:['main','rail']):['main'];for(const kind of order){const lane=document.createElement('div');lane.className='resume-lane '+kind;body.appendChild(lane);lanes.push(lane)}
   if(number===0&&def.header==='rail'){const lane=lanes.find(l=>l.classList.contains('rail'));if(lane){const h=headerNode();h.className='header-in-rail';lane.appendChild(h)}}
   const footer=document.createElement('div');footer.className='page-number';page.appendChild(footer);pages.push({page,inner,body,lanes});
  }return pages[index]}
 pageAt(0);
 // Huge unstructured contact text belongs in the content flow rather than a clipped masthead.
 if(headerBlocks.length&&def.header!=='rail'){
  const first=pages[0],h=first.inner.querySelector('header');if(h&&h.getBoundingClientRect().height>first.page.clientHeight*.35){h.remove();headerBlocks.length=0;main.unshift(contact);warnings.push('Long contact/unclassified text was flowed instead of being clipped in the header.')}
 }
 function laneAt(index,kind){const p=pageAt(index);return p.lanes.find(l=>l.classList.contains(kind))||p.lanes[0]}
 function available(lane){const p=pages.find(p=>p.lanes.includes(lane));return p.body.getBoundingClientRect().height}
 function fits(lane){window.__FORMIQO_MEASURE__={height:lane.scrollHeight,available:available(lane),kind:lane.className,children:lane.childNodes.length};return lane.scrollHeight<=available(lane)+1}
 function sliceElement(original,start,end){let offset=0;function clone(node){if(node.nodeType===Node.TEXT_NODE){const text=node.textContent,a=Math.max(0,start-offset),b=Math.min(text.length,end-offset);offset+=text.length;return b>a?document.createTextNode(text.slice(a,b)):null}const value=node.cloneNode(false);for(const child of Array.from(node.childNodes)){const result=clone(child);if(result)value.appendChild(result)}return value.childNodes.length||['BR'].includes(node.nodeName)?value:null}return clone(original)}
 function fill(seqs,kind){let pageIndex=0;for(const section of seqs){if(section.page_break_before&&(pageIndex===0||laneAt(pageIndex,kind).childNodes.length))pageIndex++;
   let needsTitle=section!==contact;for(const original of allBlocks.get(section.id)){
    let remaining=original.cloneNode(true),safety=0;
    while(remaining){if(++safety>200)throw new Error('A paragraph could not be paginated safely.');let lane=laneAt(pageIndex,kind),heading=null;const before=lane.childNodes.length;
     if(needsTitle){heading=titleOf(section);lane.appendChild(heading)}lane.appendChild(remaining);
     if(fits(lane)){remaining=null;needsTitle=false;continue}lane.removeChild(remaining);if(heading)lane.removeChild(heading);
     // Move an intact block to the next page before attempting a split.
     if(before>0){pageIndex++;needsTitle=section!==contact;continue}
     if(needsTitle){heading=titleOf(section);lane.appendChild(heading)}
     const text=remaining.textContent;let lo=1,hi=text.length,best=0;
     while(lo<=hi){const mid=Math.floor((lo+hi)/2),part=sliceElement(remaining,0,mid);lane.appendChild(part);const okay=fits(lane);lane.removeChild(part);if(okay){best=mid;lo=mid+1}else hi=mid-1}
     if(!best)throw new Error('Margins or a large header leave no room for text. Adjust layout or choose a simpler template.');
     const boundary=text.lastIndexOf(' ',best);if(boundary>best*.65)best=boundary+1;
     const first=sliceElement(remaining,0,best),rest=sliceElement(remaining,best,text.length);lane.appendChild(first);remaining=rest&&rest.textContent.length?rest:null;if(remaining)remaining.classList.add('continuation-fragment');
     pageIndex++;needsTitle=section!==contact;
    }
   }
  }}
 // Spill-over fit: when the last page holds only a small tail of content (one or two
 // short sections), tighten spacing in bounded steps so it rejoins the previous page.
 // Body text never drops below 9pt or 92% of its size; every adjustment is reported.
 const rootStyle=document.documentElement.style,base=getComputedStyle(document.documentElement);
 // Template variables are declared in pt (see document_renderer.render_document).
 const px=name=>parseFloat(base.getPropertyValue(name));
 const original={space:px('--space'),leading:px('--leading'),body:px('--body'),heading:px('--heading'),margin:px('--margin')};
 const FIT_STEPS=[{space:.75,leading:.97,body:1,margin:1},{space:.55,leading:.94,body:.97,margin:.9},{space:.4,leading:.92,body:.94,margin:.82},{space:.3,leading:.9,body:.92,margin:.75},{space:.2,leading:.88,body:.9,margin:.7}];
 function resetPages(){root.innerHTML='';pages.length=0;pageAt(0)}
 // Lanes stretch to the grid row, so measure the bottom of the last child, not scrollHeight.
 function tailRatio(){if(pages.length<2)return 0;const last=pages[pages.length-1];const top=last.body.getBoundingClientRect().top;const used=Math.max(0,...last.lanes.map(l=>l.lastElementChild?l.lastElementChild.getBoundingClientRect().bottom-top:0));return used/Math.max(1,last.body.getBoundingClientRect().height)}
 function layout(){fill(main,'main');if(two)fill(rail,'rail')}
 try{layout();
  const autoFit=cfg.style.auto_fit!==false,initialPages=pages.length,initialTail=tailRatio();
  if(autoFit&&pages.length>=2&&pages.length<=cfg.style.page_limit+1&&initialTail<=.28){
   let fitted=null;
   for(const step of FIT_STEPS){const body=Math.max(9,original.body*step.body);rootStyle.setProperty('--space',(original.space*step.space)+'pt');rootStyle.setProperty('--leading',Math.max(body*1.12,original.leading*step.leading)+'pt');rootStyle.setProperty('--body',body+'pt');rootStyle.setProperty('--margin',Math.max(30,original.margin*step.margin)+'pt');resetPages();layout();if(pages.length<initialPages){fitted=step;break}}
   if(fitted){warnings.push(`Tightened spacing${fitted.body<1?', line height and type ('+Math.round(fitted.body*100)+'%)':' and line height'} so a short overflow fits on ${pages.length} page${pages.length>1?'s':''}. All content is kept. Turn off \"Fit short overflow\" in Layout to use the original spacing.`);window.__FORMIQO_FIT__=fitted}
   else{for(const key of ['--space','--leading','--body','--margin'])rootStyle.removeProperty(key);resetPages();layout()}
  }
  for(let i=0;i<pages.length;i++)pages[i].page.querySelector('.page-number').textContent=(i+1)+' / '+pages.length;
  const pageCount=pages.length;if(pageCount>cfg.style.page_limit)warnings.push(`Content uses ${pageCount} pages, beyond your ${cfg.style.page_limit}-page preference. Nothing was removed. Adjust spacing/type, edit content, or allow another page.`);
  const rgb=def.accent.slice(1).match(/../g).map(value=>parseInt(value,16)/255).map(value=>value<=.04045?value/12.92:Math.pow((value+.055)/1.055,2.4));const luminance=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];if(1.05/(luminance+.05)<4.5)warnings.push('The selected accent has low contrast on white paper. Review headings and colored header text before sending.');
  window.__FORMIQO_READY__=true;window.__FORMIQO_RESULT__={pages:pageCount,warnings,height:root.scrollHeight,width:pages[0].page.offsetWidth};send('ready',window.__FORMIQO_RESULT__);
 }catch(error){window.__FORMIQO_ERROR__=error.message;root.innerHTML='';const problem=document.createElement('p');problem.className='document-warning';problem.textContent=error.message;root.appendChild(problem);send('error',{message:error.message});return}
 function clean(node){const copy=node.cloneNode(true);copy.removeAttribute('contenteditable');copy.removeAttribute('role');copy.removeAttribute('aria-label');for(const item of [copy,...copy.querySelectorAll('*')]){for(const attr of Array.from(item.attributes)){if(attr.name!=='href')item.removeAttribute(attr.name)}}return copy.innerHTML}
 function sectionHTML(id){const groups=new Map();for(const block of Array.from(root.querySelectorAll('[data-section]')).filter(n=>n.dataset.section===id)){const key=Number(block.dataset.block);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(block)}return Array.from(groups.entries()).sort((a,b)=>a[0]-b[0]).map(([index,parts])=>{if(parts.length===1)return clean(parts[0]);const original=allBlocks.get(id)?.[index]?.firstElementChild;const tag=original?.tagName;const children=parts.map(part=>part.firstElementChild);const wrapper=document.createElement('div');if(tag==='P'&&children.every(child=>child?.tagName==='P')){const paragraph=document.createElement('p');paragraph.innerHTML=children.map(child=>child.innerHTML).join('');wrapper.appendChild(paragraph);return clean(wrapper)}if(['UL','OL'].includes(tag)&&children.every(child=>child?.tagName===tag&&child.children.length===1&&child.firstElementChild.children.length===1&&child.firstElementChild.firstElementChild.tagName==='P')){const list=document.createElement(tag),li=document.createElement('li'),p=document.createElement('p');p.innerHTML=children.map(child=>child.firstElementChild.firstElementChild.innerHTML).join('');li.appendChild(p);list.appendChild(li);wrapper.appendChild(list);return clean(wrapper)}return parts.map(clean).join('')}).join('')}
 if(cfg.interactive){let selectionTimer;document.addEventListener('selectionchange',()=>{clearTimeout(selectionTimer);selectionTimer=setTimeout(()=>{const selected=window.getSelection();if(!selected||selected.isCollapsed)return;const a=selected.anchorNode?.parentElement?.closest('[data-section]'),b=selected.focusNode?.parentElement?.closest('[data-section]');if(a&&b&&a.dataset.section===b.dataset.section)send('selection',{sectionId:a.dataset.section,text:selected.toString().trim().slice(0,12000)})},70)})}
 if(cfg.interactive){try{document.execCommand('defaultParagraphSeparator',false,'p')}catch{}root.addEventListener('focusin',()=>send('focus',{active:true}));root.addEventListener('focusout',()=>send('focus',{active:false}))}
 if(cfg.interactive){root.addEventListener('input',event=>{const block=event.target.closest('[data-section]');if(block)dirtySections.add(block.dataset.section);send('dirty')});root.addEventListener('click',event=>{const link=event.target.closest('a');if(link)event.preventDefault();const block=event.target.closest('[data-section]');if(block)send('select',{sectionId:block.dataset.section})});root.addEventListener('paste',event=>{event.preventDefault();document.execCommand('insertText',false,event.clipboardData.getData('text/plain'))});root.addEventListener('focusout',event=>{const block=event.target.closest('[data-section]');if(!block||!dirtySections.has(block.dataset.section))return;send('edit',{sectionId:block.dataset.section,html:sectionHTML(block.dataset.section)});dirtySections.delete(block.dataset.section)})}
 else root.addEventListener('click',event=>{if(event.target.closest('a'))event.preventDefault()});
 window.addEventListener('message',event=>{if(event.source!==parent||event.data?.token!==cfg.token)return;if(event.data.kind==='select'){root.querySelectorAll('.selected-section').forEach(n=>n.classList.remove('selected-section'));root.querySelectorAll('[data-section]').forEach(n=>{if(n.dataset.section===event.data.sectionId)n.classList.add('selected-section')})}if(event.data.kind==='snapshot'){const changed=sections.filter(s=>dirtySections.has(s.id)).map(s=>({id:s.id,html:sectionHTML(s.id)}));send('snapshot',{requestId:event.data.requestId,sections:changed});dirtySections.clear()}if(event.data.kind==='print')window.print()});
})();
