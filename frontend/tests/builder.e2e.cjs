/* Real Module 3 workflow: no AI/provider mocks, synthetic user-entered facts only. */
const {chromium}=require('playwright');
const AxeBuilder=require('@axe-core/playwright').default;
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const base=process.env.E2E_BASE_URL||'http://localhost:5173';
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
 const context=await browser.newContext({viewport:{width:1536,height:1080}});const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));const dir=path.resolve('test-results');await fs.mkdir(dir,{recursive:true});let originalID,copyID;
 const nav=()=>page.getByRole('navigation',{name:'Resume builder steps'});
 const go=async(name)=>nav().getByRole('button',{name:new RegExp(name)}).click();
 const fill=async(id,value)=>page.locator('[id="builder-'+id+'"]').fill(value);
 const next=async()=>{await page.getByRole('button',{name:/^(Continue|Save & continue)$/}).click();await page.getByRole('status').filter({hasText:'Saved · builder version'}).waitFor()};
 try{
  await page.goto(base+'/app/builder/intake');await page.getByRole('heading',{name:'Contact information',exact:true}).waitFor();
  assert.equal(await page.locator('[id="builder-contact.name"]').inputValue(),'');
  await page.getByRole('button',{name:'Continue',exact:true}).click();await page.getByRole('alert').filter({hasText:'Add your full name'}).waitFor();
  await fill('contact.name','Avery Morgan');await fill('contact.email','avery@example.com');await fill('contact.location','Remote');await fill('contact.website','https://example.com/portfolio');
  await page.screenshot({path:path.join(dir,'builder-contact-desktop.png'),fullPage:true});
  await next();await page.getByRole('heading',{name:'Your direction & summary'}).waitFor();originalID=new URL(page.url()).searchParams.get('resume');assert.ok(originalID);
  await fill('target_role','Software Engineer');await fill('summary','Developed accessible reporting tools and reliable services using verified engineering experience.');
  await page.getByLabel('Autosave to temporary workspace').check();await page.getByRole('status').filter({hasText:'Saved · builder version 2'}).waitFor({timeout:20000});await page.getByLabel('Autosave to temporary workspace').uncheck();
  await page.reload();await page.getByRole('heading',{name:'Your direction & summary'}).waitFor();assert.match(await page.locator('[id="builder-summary"]').inputValue(),/verified engineering/);
  await next();await page.getByRole('button',{name:'Add work experience',exact:true}).click();
  await fill('experience.0.title','Engineer');await fill('experience.0.employer','Verified Systems');await fill('experience.0.start','2023-01');await fill('experience.0.end','2022-01');
  await page.getByRole('button',{name:'Save & continue',exact:true}).click();await page.getByRole('alert').filter({hasText:'End date cannot precede'}).waitFor();
  await page.getByLabel('I currently work here').check();assert.equal(await page.locator('[id="builder-experience.0.end"]').inputValue(),'');
  await fill('experience.0.highlights','Built Python services for actual customer workflows.\nTested deployment checks for verified tools.');
  await page.getByRole('button',{name:'Remove role 1'}).click();await page.getByRole('button',{name:'Cancel',exact:true}).click();assert.ok(await page.locator('[id="builder-experience.0.title"]').isVisible());
  await next();await page.getByRole('button',{name:'Add education',exact:true}).click();await fill('education.0.institution','Actual College');await fill('education.0.qualification','Computer Science coursework');await fill('education.0.start','2020');await fill('education.0.end','2022');
  await next();await fill('skills','Python, React, SQL');await next();
  await page.getByRole('button',{name:'Add project',exact:true}).click();await fill('projects.0.name','Reporting Toolkit');await fill('projects.0.url','https://example.com/project');await fill('projects.0.technologies','Python, SQL');await fill('projects.0.highlights','Built internal reporting tools for actual team workflows.');await next();
  await page.getByRole('button',{name:'Add certification',exact:true}).click();await fill('certifications.0.name','Verified Training');await fill('certifications.0.issuer','Actual Provider');await fill('certifications.0.date','2024');await fill('achievements','Delivered an actual internal workshop.');await next();
  await page.getByRole('button',{name:'Add custom section',exact:true}).click();await fill('additional.0.title','Volunteer Experience');await fill('additional.0.content','Organized a local community workshop.');
  for(let i=0;i<3;i++)await page.getByRole('button',{name:'Move Technical Skills up',exact:true}).click();
  await next();await page.getByRole('heading',{name:'Choose your presentation'}).waitFor();assert.equal(await page.getByRole('radio').count(),18);
  await page.getByRole('button',{name:'Preview Modern Professional',exact:true}).click();await page.getByRole('dialog').getByRole('heading',{name:'Modern Professional',exact:true}).waitFor();await page.getByRole('button',{name:'Use this template',exact:true}).click();
  assert.ok(await page.getByRole('radio',{name:'Modern Professional',exact:true}).isChecked());
  await page.getByRole('radio',{name:'Software Engineer',exact:true}).check();await page.waitForTimeout(1000);
  await page.screenshot({path:path.join(dir,'builder-templates-desktop.png'),fullPage:true});
  const templateAxe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(path.join(dir,'builder-templates-accessibility.json'),JSON.stringify(templateAxe.violations,null,2));assert.equal(templateAxe.violations.length,0,templateAxe.violations.map(v=>v.id).join(', '));
  await next();await page.getByRole('heading',{name:'Ready for your next chapter.'}).waitFor();
  await page.getByLabel(/I reviewed the names, dates/).check();
  const pdfPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Download PDF',exact:true}).click();await (await pdfPromise).saveAs(path.join(dir,'builder-export.pdf'));assert.equal((await fs.readFile(path.join(dir,'builder-export.pdf'))).subarray(0,5).toString(),'%PDF-');
  const docxPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Download DOCX',exact:true}).click();await (await docxPromise).saveAs(path.join(dir,'builder-export.docx'));assert.ok((await fs.stat(path.join(dir,'builder-export.docx'))).size>1000);
  await page.getByRole('button',{name:'Actual PDF preview',exact:true}).click();await page.getByTitle('Generated builder PDF').waitFor();assert.match(await page.getByTitle('Generated builder PDF').getAttribute('src'),/^blob:/);await page.getByRole('button',{name:'Close dialog',exact:true}).click();
  await page.screenshot({path:path.join(dir,'builder-review-desktop.png'),fullPage:true});
  const reviewAxe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();await fs.writeFile(path.join(dir,'builder-review-accessibility.json'),JSON.stringify(reviewAxe.violations,null,2));assert.equal(reviewAxe.violations.length,0,reviewAxe.violations.map(v=>v.id).join(', '));
  await page.reload();await page.getByRole('heading',{name:'Ready for your next chapter.'}).waitFor();
  const saved=await (await context.request.get(base+'/api/builder/'+originalID)).json();assert.equal(saved.data.template,'technical');assert.equal(saved.data.contact.name,'Avery Morgan');assert.ok(saved.content.sections.findIndex(s=>s.title==='Technical Skills')<saved.content.sections.findIndex(s=>s.title==='Experience'));
  for(const width of [320,375,768,1280]){await page.setViewportSize({width,height:950});await page.waitForTimeout(100);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow at '+width);await page.screenshot({path:path.join(dir,'builder-review-'+width+'.png'),fullPage:true})}
  await page.setViewportSize({width:1536,height:1080});await page.getByRole('button',{name:'Check ATS compatibility',exact:true}).click();await page.locator('#resume-text').waitFor();assert.match(await page.locator('#resume-text').inputValue(),/Avery Morgan/);await page.getByRole('button',{name:'Analyze my resume',exact:true}).click();await page.getByRole('heading',{name:'A clear view of what your resume communicates.'}).waitFor();
  await page.getByRole('link',{name:'Open improvement studio',exact:true}).click();await page.getByRole('button',{name:/^Professional Summary/}).click();await page.getByRole('textbox',{name:'Professional Summary content'}).fill('Newer editor content that the builder must preserve.');await page.getByRole('button',{name:'Save draft',exact:true}).click();await page.getByRole('status').filter({hasText:/Saved.*version/}).waitFor();
  await page.goto(base+'/app/builder/intake?resume='+originalID);await page.getByRole('alert').filter({hasText:'A newer editor or checker draft exists.'}).waitFor();assert.ok(await page.getByRole('button',{name:'Save draft',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Save form as separate copy',exact:true}).click();await page.waitForURL(url=>url.searchParams.get('resume')!==originalID);copyID=new URL(page.url()).searchParams.get('resume');assert.ok(copyID&&copyID!==originalID);
  const original=await (await context.request.get(base+'/api/resumes/'+originalID)).json();assert.match(original.text,/Newer editor content/);
  await page.getByRole('link',{name:'My Documents',exact:true}).click();await page.getByRole('heading',{name:'My documents',exact:true}).waitFor();await page.getByRole('link',{name:/Build Avery Morgan/}).nth(1).waitFor();assert.ok(await page.getByRole('link',{name:/Build Avery Morgan/}).count()>=2);
  for(const id of [originalID,copyID]){assert.equal((await context.request.delete(base+'/api/resumes/'+id)).status(),204);assert.equal((await context.request.get(base+'/api/builder/'+id)).status(),404)}
  assert.deepEqual(errors,[]);console.log('PASS Module 3: ten guided steps, required/optional fields, dates, autosave/reload, entry controls/order, template preview/select, actual PDF/DOCX + PDF preview, responsiveness, ATS/editor handoff, conflict-safe copy, document library/deletion, axe template/review pages: 0 violations.');
 }catch(error){await page.screenshot({path:path.join(dir,'builder-failure.png'),fullPage:true}).catch(()=>{});await fs.writeFile(path.join(dir,'builder-failure.txt'),await page.locator('body').innerText().catch(()=>''));throw error}
 finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
