/* Real browser + running API integration checks. Only synthetic resume data. */
const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const base = process.env.E2E_BASE_URL || 'http://localhost:5173';
const sample = `Jordan Rivera
jordan@example.com
Professional Summary
Software engineer building accessible tools for people and reliable systems for teams.
Experience
Acme Systems | Software Engineer | 2021 - Present
Developed Python services to support customer workflows and automated reliable deployment checks.
Projects
Built a React dashboard using PostgreSQL to present accessible performance reports for internal teams.
Education
Computer Science coursework
Skills
Python, React, SQL, PostgreSQL, Git, Docker
`;
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const artifacts = path.resolve('test-results');
  await fs.mkdir(artifacts, { recursive: true });
  try {
    await page.goto(base);
    await page.getByRole('button', { name: 'Browse files' }).waitFor();
    await page.screenshot({ path: path.join(artifacts, 'landing-desktop.png'), fullPage: true });
    await page.getByRole('link', { name: 'Check My Resume', exact: true }).click();
    await page.getByRole('button', { name: 'Browse files' }).waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.querySelector('button:disabled')?.textContent?.includes('Browse'));
    await page.screenshot({ path: path.join(artifacts, 'checker-desktop.png'), fullPage: true });
    await page.getByLabel('Upload resume PDF, DOCX or TXT').setInputFiles({ name: 'synthetic-resume.txt', mimeType: 'text/plain', buffer: Buffer.from(sample) });
    await page.locator('#resume-text').waitFor({ timeout: 120000 });
    assert.match(await page.locator('#resume-text').inputValue(), /Developed Python/);
    await page.getByRole('button', { name: 'Analyze my resume' }).click();
    await page.waitForURL('**/app/results/**', { timeout: 60000 });
    await page.getByRole('heading', { name: 'A clear view of what your resume communicates.' }).waitFor();
    const originalURL = page.url();
    assert.ok(await page.getByRole('img', { name: /Estimated ATS Compatibility Score/ }).isVisible());
    await page.getByRole('button', { name: /Structure & organization/ }).click();
    await page.locator('.analysis-checks').waitFor();
    assert.match(await page.locator('.analysis-checks').innerText(), /points/);
    await page.screenshot({ path: path.join(artifacts, 'results-desktop.png'), fullPage: true });
    const report = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    await fs.writeFile(path.join(artifacts, 'accessibility-results.json'), JSON.stringify(report.violations, null, 2));
    assert.equal(report.violations.length, 0, report.violations.map(v => v.id + ': ' + v.description).join('\n'));
    const reportDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Report', exact:true }).click();
    const downloaded = await reportDownload;
    const reportPath = path.join(artifacts, 'analysis.json');
    await downloaded.saveAs(reportPath);
    const analysis = JSON.parse(await fs.readFile(reportPath, 'utf8'));
    assert.equal(analysis.overall_score, analysis.categories.reduce((n, c) => n + c.score, 0));
    await page.goto(base + '/app/checker?resume=' + analysis.resume_id + '&from=' + analysis.id);
    await page.locator('#resume-text').waitFor();
    await page.locator('#resume-text').fill(sample.replace('jordan@example.com', ''));
    await page.getByRole('button', { name: 'Save draft' }).click();
    await page.getByRole('status').filter({ hasText: 'Resume text saved' }).waitFor();
    await page.reload();
    await page.locator('#resume-text').waitFor();
    assert.ok(!(await page.locator('#resume-text').inputValue()).includes('jordan@example.com'));
    await page.getByRole('button', { name: 'Analyze my resume' }).click();
    await page.waitForURL('**/app/results/**');
    await page.locator('.analysis-comparison').waitFor();
    // The delta must equal the real difference between the two saved analyses (no hard-coded rubric value).
    {const updatedId=page.url().split('/results/')[1].split('?')[0];const updated=await (await context.request.get(base+'/api/ats/results/'+updatedId)).json();const delta=updated.overall_score-analysis.overall_score;assert.ok(delta<0,'Removing the only contact channel must lower the score');assert.match(await page.locator('main').innerText(),new RegExp(String(delta)+' points'))}
    await page.goto(base + '/app/checker?resume=' + analysis.resume_id + '&from=' + page.url().split('/results/')[1].split('?')[0]);
    await page.locator('#resume-text').waitFor();
    await page.getByRole('button', { name: 'Original', exact: true }).click();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.ok(!(await page.locator('#resume-text').inputValue()).includes('jordan@example.com'));
    await page.getByRole('button', { name: 'Original', exact: true }).click();
    await page.getByRole('button', { name: 'Restore original' }).click();
    assert.match(await page.locator('#resume-text').inputValue(), /jordan@example.com/);
    await page.getByRole('radio', { name: /Match a job description/ }).check();
    await page.locator('#job-description').fill('Required: Python and AWS infrastructure engineering. Preferred: Kubernetes. Responsibilities: build services with Python and AWS.');
    await page.getByRole('button', { name: 'Analyze my resume' }).click();
    await page.waitForURL('**/app/results/**');
    await page.getByRole('button', { name: 'Job keywords',exact:true }).click();
    assert.ok(await page.getByText('aws', { exact: true }).isVisible());
    for (const width of [320, 375, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(100);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Horizontal overflow at ' + width);
      await page.screenshot({ path: path.join(artifacts, 'results-' + width + '.png'), fullPage: true });
    }
    await page.setViewportSize({ width: 375, height: 900 });
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('dialog').waitFor();
    await page.getByRole('dialog').getByRole('link', { name: 'My Documents' }).click();
    await page.getByRole('heading', { name: 'My documents' }).waitFor();
    await page.getByRole('button', { name: 'Delete synthetic-resume.txt' }).click();
    await page.getByRole('button', { name: 'Delete permanently' }).click();
    await page.getByRole('heading', { name: 'Your next chapter starts here.' }).waitFor();
    await page.goto(originalURL);
    await page.getByRole('alert').filter({ hasText: 'Analysis not found' }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: upload → extraction → score → details → real download → edit/save/reload → recalculation → original review → job match → responsive navigation → deletion; axe results page: 0 violations.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
