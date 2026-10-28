"""Versioned lexical/structural rubric, not an employer ATS simulator.

AI contributes separate cited semantic observations, never arbitrary numbers.
Optional degrees, certifications, metrics and phone numbers are not mandatory.
All heuristics and their limits are returned alongside category scores.
"""
import hashlib
import json
import re
from collections import Counter
from .config import settings
from .schemas import Category, Finding
from .ats_terms import match_terms, contains as term_contains

LABELS = {'structure': 'Structure & organization', 'keywords': 'General relevance', 'experience': 'Experience & achievements', 'skills': 'Skills presentation', 'readability': 'Readability & formatting', 'contact': 'Contact & completeness'}
HEADINGS = {'summary': r'(?:professional |career )?(?:summary|profile|objective)', 'experience': r'(?:professional |work |employment |relevant )?(?:experience|history)', 'education': r'education|academic background', 'skills': r'(?:technical |core |key )?(?:skills|competencies|expertise)', 'projects': r'(?:personal |selected |academic )?projects', 'certifications': r'certifications|certificates|licenses', 'additional': r'achievements|publications|languages|volunteer experience|awards|interests'}
STOP = set('the and for with that this from your you our are will have has can not all their they into work role team candidate required requirements preferred qualifications experience knowledge ability skills strong excellent including using must years year job responsibilities seeking company about also such demonstrate demonstrated proficiency understanding bachelor degree minimum plus least related field relevant position working support develop development looking good new more one within provide through opportunity candidates hiring or of to in on a an is as be by at it we us do if'.split())
TECH_TERMS = ['python', 'javascript', 'typescript', 'react', 'angular', 'vue', 'node.js', 'java', 'c++', 'c#', 'sql', 'postgresql', 'mysql', 'mongodb', 'redis', 'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'linux', 'git', 'figma', 'excel', 'tableau', 'power bi', 'salesforce', 'sap', 'machine learning', 'deep learning', 'data analysis', 'data science', 'project management', 'customer service', 'communication', 'leadership', 'agile', 'scrum', 'accounting', 'marketing', 'seo', 'ux', 'ui', 'fastapi', 'pytorch', 'tensorflow', 'html', 'css']
VERBS = r'\b(?:built|developed|designed|implemented|led|managed|created|delivered|improved|reduced|increased|automated|analyzed|launched|organized|supported|maintained|coordinated|tested|resolved|trained|collaborated|conducted|researched|optimized|engineered|produced|wrote)\b'


ACTION_VERBS = set("""achieved accelerated administered advised analyzed architected assembled assessed automated balanced built calculated championed
closed coached collaborated completed conducted configured consolidated coordinated created cut debugged decreased defined delivered deployed designed developed
diagnosed directed documented doubled drafted drove eliminated enabled engineered established evaluated executed expanded facilitated forecasted founded generated
grew guided handled hired identified implemented improved increased influenced initiated installed instituted integrated introduced investigated launched led
maintained managed mentored migrated modernized monitored negotiated onboarded operated optimized orchestrated organized oversaw partnered performed piloted planned
prepared presented prioritized processed produced programmed prototyped published raised rebuilt redesigned reduced refactored replaced researched resolved restructured
reviewed revamped saved scaled scheduled secured shipped simplified sold spearheaded standardized streamlined strengthened supervised supported surveyed taught
tested trained transformed translated tripled troubleshot unified upgraded validated wrote""".split())
WEAK = r'\b(?:responsible for|worked on|helped with|helped to|duties included|tasked with|in charge of|assisted with|involved in)\b'
METRIC = r'(?:\d[\d,.]*\s*(?:%|percent|x\b|k\b|m\b|users|customers|clients|people|staff|engineers|hours|days|weeks|projects|stores|records|requests|transactions|teams?|countries|sites|locations|million|billion|thousand)|[$\u20ac\u00a3\u20b9]\s?\d|\b\d{2,}[\d,]*\b(?![-\u2013/]\d)(?!\s*(?:-|\u2013|to)\s*(?:19|20)\d{2}))'
SOFT_FILLER = {'hard worker', 'team player', 'hardworking', 'motivated', 'self-motivated', 'fast learner', 'quick learner', 'detail-oriented', 'detail oriented', 'punctual', 'reliable', 'honest', 'go-getter', 'people person', 'multitasking', 'passionate'}
DATE_LINE = re.compile(r'^(?:[A-Za-z]{3,9}\.?\s+)?(?:19|20)\d{2}\s*(?:-|\u2013|\u2014|to)\s*(?:(?:[A-Za-z]{3,9}\.?\s+)?(?:19|20)\d{2}|present|current|now)\b', re.I)


DATE_RANGE = re.compile(r'(?:19|20)\d{2}\s*(?:-|\u2013|\u2014|to)\s*(?:(?:[A-Za-z]{3,9}\.?\s+)?(?:19|20)\d{2}|present|current|now)\b', re.I)


def is_statement(line: str):
    """An achievement/description line: a bullet, or a sentence-like line of 6+ words.

    Entry titles ("Engineer | Company | 2021 - Present", "Associate, Store, 2021 -
    Present") and date lines are context, not statements to grade.
    """
    value = re.sub(r'^[\u2022\-\*\u00b7]\s*', '', line).strip()
    if not value or DATE_LINE.match(value):
        return False
    if re.match(r'^[\u2022\-\*\u00b7]\s', line):
        return len(value.split()) >= 3
    if DATE_RANGE.search(value) and len(value.split()) <= 14 and not re.search(r'[.!?]$', value):
        return False
    if '|' in value and len(value.split()) <= 14:
        return False
    return len(value.split()) >= 6


def starts_with_action(line: str):
    """True when a statement opens with a past-tense contribution verb, not a vague lead-in."""
    value = re.sub(r'^[\u2022\-\*\u00b7]\s*', '', line).strip()
    if re.match(WEAK, value, re.I):
        return False
    first = re.split(r'[\s,;:]+', value, maxsplit=1)[0].lower().strip('.')
    if '-' in first:
        return False  # compound adjectives such as customer-focused, data-driven
    return first in ACTION_VERBS or (first.endswith('ed') and len(first) > 4 and first not in {'need', 'based', 'skilled', 'experienced', 'interested', 'detailed', 'dedicated', 'motivated', 'talented', 'certified', 'licensed', 'focused', 'seasoned', 'accomplished', 'qualified', 'driven'})


def split_skills(text: str):
    return [item.strip(' .') for item in re.split(r'[,;|\u2022\u00b7/\n]+|\s{2,}', text) if len(item.strip(' .')) >= 2][:80]


def length_ratio(count: int):
    if count < 200:
        return count / 200
    if count > 1100:
        return max(.5, 1 - (count - 1100) / 1100)
    return 1.0


HEADING_PREFIX = re.compile(r'^(?:\d{1,2}[.)]?|[ivx]{1,4}[.)]|[#>/\u00a7\u2022|-]+)\s+', re.I)


def heading_key(line: str):
    """Return the standard section key for a heading line, or None.

    Accepts plain, uppercase, colon-terminated and numbered/decorated headings
    ("02 Experience", "II. Education", "// Skills") used by technical layouts.
    """
    value = re.sub(r'\s+', ' ', line.strip().strip(':').strip()).lower()
    value = HEADING_PREFIX.sub('', value, count=1).strip().strip(':').strip()
    if not value or len(value) > 60:
        return None
    return next((key for key, pattern in HEADINGS.items() if re.fullmatch(pattern, value)), None)


def contains(text: str, term: str):
    return bool(re.search(r'(?<![\w])' + re.escape(term) + r'(?![\w])', text, re.I))


def keywords(jd: str, text: str, sections: dict | None = None, title: str = ''):
    """Weighted JD term coverage (see app.ats_terms). Backwards-compatible keys are kept."""
    matched = match_terms(jd, text, sections, title)
    terms = matched['terms']
    groups = {name: lines for name, lines in matched['groups'].items() if name != 'general' or lines}
    found = [t['term'] for t in terms if t['present']]
    missing = [t['term'] for t in terms if not t['present']]
    contexts = [{'term': t['term'], 'present': t['present'], 'kind': t['kind'], 'importance': t['importance'], 'weight': t['weight'], 'matched_as': t['matched_as'], 'where': t['where'], 'contexts': t['contexts'], 'requires_confirmation': t['requires_confirmation']} for t in terms]
    return {'found': found, 'missing': missing, 'shared_skills': [t['term'] for t in terms if t['present'] and t['kind'] == 'skill or tool'],
            'confirmation_required': missing, 'groups': groups, 'contexts': contexts, 'candidate_count': len(terms),
            'weighted_coverage': matched['weighted_coverage'], 'evidence_coverage': matched['evidence_coverage'],
            'required_found': matched['required_found'], 'required_total': matched['required_total'],
            'missing_required': [t['term'] for t in terms if not t['present'] and t['importance'] == 'required'],
            'method': 'Terms come from a published skills/tools lexicon with aliases, technical tokens and repeated phrases in the job description. Each term is weighted by where it appears (required 3, responsibilities 2, preferred 1, plus repetition and title). Grouping is a heading/clause heuristic; review the original description.'}


def analyze(text: str, metadata: dict, job_description: str = '', mode: str = 'general'):
    weights = settings.scoring_weights
    version = 'local-rubric-2.0-' + hashlib.sha256(json.dumps(weights, sort_keys=True).encode()).hexdigest()[:8]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    words = re.findall(r'\b[\w+#.-]+\b', text)
    sections = {}
    current = None
    for line in lines:
        match = heading_key(line)
        if match:
            current = match
            sections.setdefault(match, [])
        elif current:
            sections[current].append(line)
    checks = {k: [] for k in weights}
    findings = []
    strengths = []

    def check(category, label, passed, fraction, evidence):
        checks[category].append({'label': label, 'passed': bool(passed), 'fraction': fraction, 'evidence': evidence})

    def issue(category, priority, title, evidence, why, correction, example=None, confirmation=False):
        affected=next((name.title() for name,values in sections.items() if any(evidence and evidence in line for line in values)),{'contact':'Contact information','readability':'Document extraction','structure':'Section organization','keywords':'Relevant resume sections','skills':'Skills'}.get(category,'Experience / Projects'))
        findings.append(Finding(id=f'finding-{len(findings)+1}', category=category, section=affected, priority=priority, title=title, evidence=evidence, why=why, correction=correction, example=example, requires_confirmation=confirmation).model_dump())

    def graded(category, label, ratio, fraction, evidence):
        ratio = max(0.0, min(1.0, float(ratio)))
        checks[category].append({'label': label, 'passed': ratio >= .999, 'fraction': fraction, 'credit_ratio': round(ratio, 4), 'evidence': evidence})

    # Evidence lines: bullets and sentences inside experience/projects. Entry title
    # lines ("Engineer | Company", dates) are context, not achievement statements.
    evidence_lines = sections.get('experience', []) + sections.get('projects', [])
    statements = [line for line in evidence_lines if is_statement(line)]

    # ---- Structure (substantive sections, each with real content) ----
    core = [key for key in ('experience', 'projects', 'education', 'skills', 'summary') if key in sections]
    standard = len(sections) >= 2
    graded('structure', 'Standard sections recognized (summary, experience/projects, education, skills)', min(1, len(core) / 4), .45, ', '.join(sections) or 'No exact standard headings recognized')
    filled = [key for key, values in sections.items() if len(' '.join(values).split()) >= 3]
    populated = bool(sections) and len(filled) == len(sections)
    graded('structure', 'Recognized sections contain substantive text', len(filled) / max(1, len(sections)) if sections else 0, .3, 'Sparse/empty sections: ' + ', '.join(k for k in sections if k not in filled) if not populated else 'Each recognized section contains at least a short line of content')
    has_evidence = bool(sections.get('experience') or sections.get('projects') or sections.get('education'))
    check('structure', 'Experience, projects, or education is organized in a named section', has_evidence, .25, 'Alternative paths are accepted; no specific degree or employment is required')
    if not standard:
        issue('structure', 'high', 'Section boundaries are not clearly recognized', 'Recognized headings: ' + (', '.join(sections) or 'none'), 'Predictable headings help readers and parsers locate content. Custom headings may be missed by this checker.', 'Add a plain heading such as Experience, Projects, Education, or Skills above existing relevant content. Do not add a section you do not need.')
    else:
        strengths.append('Recognizable section headings organize your resume.')
    if not populated and sections:
        issue('structure', 'medium', 'A recognized section is nearly empty', ', '.join(k for k in sections if k not in filled), 'A heading with little content offers no supporting information.', 'Complete the section with verified details or remove the unused heading.')

    # ---- Keywords / relevance ----
    kw = keywords(job_description, text, sections) if mode == 'job' else {'found': [], 'missing': [], 'shared_skills': [], 'confirmation_required': [], 'groups': {}, 'contexts': [], 'candidate_count': 0, 'method': 'No job description supplied; general relevance is assessed from vocabulary depth and evidence instead.'}
    if mode == 'job' and kw['candidate_count'] >= 3:
        graded('keywords', 'Weighted job-term coverage (required terms count 3x, preferred 1x)', kw['weighted_coverage'], .7, f"{len(kw['found'])} of {kw['candidate_count']} terms explicit; {round(kw['weighted_coverage'] * 100)}% of weighted importance. Not a qualification verdict.")
        graded('keywords', 'Matched terms are demonstrated in experience or projects, not only listed', kw['evidence_coverage'], .3, f"{round(kw['evidence_coverage'] * 100)}% of matched weight appears in experience/project evidence")
        if kw['missing_required']:
            issue('keywords', 'high', 'Required job terms are not explicit', ', '.join(kw['missing_required'][:12]), 'Terms in the requirements section carry the most weight. A missing word is a visibility gap, not evidence that you lack the skill.', 'Confirm which required terms match your actual experience, then show them in an experience or project bullet where you used them.', confirmation=True)
        other = [term for term in kw['missing'] if term not in kw['missing_required']]
        if other:
            issue('keywords', 'medium', 'Some job-description terms are not explicit', ', '.join(other[:12]), 'Missing words are a visibility gap, not evidence that you lack a skill or qualification.', 'Confirm which terms match your actual experience. Incorporate only verified terms naturally in an existing section.', confirmation=True)
        listed_only = [c['term'] for c in kw['contexts'] if c['present'] and c['where'] == ['skills']]
        if listed_only:
            issue('keywords', 'low', 'Some matched terms appear only in the skills list', ', '.join(listed_only[:10]), 'A listed skill is easy to find; a bullet that shows where you used it is more convincing to recruiters.', 'Where accurate, mention the tool in the experience or project bullet that used it.', confirmation=True)
    elif mode == 'job':
        check('keywords', 'No reliable candidate terms detected; neutral credit', True, 1, 'Not enough skills, tools or repeated phrases to make a reliable keyword comparison')
    else:
        substantive = {w.lower() for w in words if len(w) >= 4 and w.lower() not in STOP}
        graded('keywords', 'Concrete content vocabulary (distinct non-stopword terms)', len(substantive) / 100, .4, f'{len(substantive)} distinct terms; full credit at 100. A depth proxy, not semantic relevance')
        graded('keywords', 'Body length suits a one-to-two page resume (200-1100 words)', length_ratio(len(words)), .3, f'{len(words)} words')
        skill_terms = [line for line in sections.get('skills', [])]
        named = len(split_skills(' '.join(skill_terms)))
        graded('keywords', 'Role evidence and named skills give context', (.5 if has_evidence else 0) + .5 * min(1, named / 6), .3, f"{'Evidence section present' if has_evidence else 'No evidence section'}; {named} named skills")

    # ---- Experience & achievements: graded across statements ----
    if evidence_lines:
        n = max(1, len(statements))
        action = [line for line in statements if starts_with_action(line)]
        weak = [line for line in evidence_lines if re.search(WEAK, line, re.I)]
        detailed = [line for line in statements if 8 <= len(line.split()) <= 45]
        quantified = [line for line in statements if re.search(METRIC, line, re.I)]
        graded('experience', 'Statements lead with a strong action verb', len(action) / n if statements else 0, .35, f'{len(action)} of {len(statements)} statements' + (f' — e.g. "{action[0][:140]}"' if action else ''))
        graded('experience', 'Statements give context (8-45 words each)', len(detailed) / n if statements else 0, .2, f'{len(detailed)} of {len(statements)} statements are within 8-45 words')
        graded('experience', 'Outcomes or scale are stated where known', min(1, len(quantified) / max(1, .4 * n)) if statements else 0, .25, f'{len(quantified)} of {len(statements)} statements include a number, percentage, amount or scale; full credit at 40%')
        graded('experience', 'Avoids vague lead-ins (responsible for, worked on, helped with)', 1 - len(weak) / max(1, len(evidence_lines)) if weak else 1, .2, weak[0][:300] if weak else 'No tracked vague phrases detected')
        if weak or (statements and len(action) < .5 * len(statements)) or not statements:
            quote = weak[0] if weak else next((line for line in statements if not starts_with_action(line)), evidence_lines[0])
            issue('experience', 'medium', 'Lead with what you did', quote[:400], 'Statements that begin with an action and include context are easier to evaluate than responsibility lists.', 'Start with a verb that names your actual contribution, then add how and the verified outcome. Do not invent metrics.', 'Developed [actual deliverable] using [verified tools] to support [actual purpose].', True)
        if action:
            strengths.append('Experience or project statements lead with concrete action language.')
        if statements and len(quantified) < .4 * len(statements):
            target = next((line for line in statements if not re.search(METRIC, line, re.I)), statements[0])
            issue('experience', 'low', 'Add verified scale or outcomes where you know them', target[:300], 'Numbers such as users served, time saved or volume handled help readers judge impact. Not every statement needs one.', 'If you know an actual outcome, add it. Otherwise describe the qualitative result. Never estimate figures you cannot support.', confirmation=True)
        elif quantified:
            strengths.append('Several statements state verified scale or outcomes.')
    else:
        check('experience', 'No applicable experience/projects section; neutral credit', True, 1, 'No employment history was required; education-only resumes are not penalized for missing work metrics')

    # ---- Skills ----
    skill_lines = sections.get('skills', [])
    skill_items = split_skills(' '.join(skill_lines))
    if mode == 'job' and kw.get('candidate_count', 0) >= 3:
        skill_terms = [c for c in kw['contexts'] if c['kind'] == 'skill or tool']
        shared = [c for c in skill_terms if c['present']]
        if skill_terms:
            graded('skills', 'Job-listed skills and tools explicitly present', sum(c['weight'] for c in shared) / sum(c['weight'] for c in skill_terms), .6, f'{len(shared)} of {len(skill_terms)} skills/tools from the job description, weighted by importance')
        else:
            check('skills', 'No skills/tools in the job description; neutral credit', True, .6, 'The description names no lexicon skills or tools')
        graded('skills', 'A skills section names concrete tools or methods', min(1, len(skill_items) / 6), .4, f'{len(skill_items)} named skills' if skill_lines else 'No skills section; skills may still appear in experience')
    elif skill_lines:
        vague = [item for item in skill_items if item.lower() in SOFT_FILLER]
        concrete = [item for item in skill_items if item.lower() not in SOFT_FILLER]
        graded('skills', 'Skills section names concrete tools, methods or domains', min(1, len(concrete) / 6), .6, f'{len(concrete)} concrete skills' + (f'; generic: {", ".join(vague[:4])}' if vague else ''))
        graded('skills', 'Skills lines are scannable (under 60 words each)', 1 if all(len(line.split()) <= 60 for line in skill_lines) else .5, .4, 'A readability heuristic, not an ATS requirement')
        if len(concrete) < 4:
            issue('skills', 'medium', 'Name the specific tools and methods you use', ', '.join(skill_items[:6]) or skill_lines[0][:200], 'Generic traits such as "hard worker" are not searchable skills. Recruiters and ATS filters look for tools, methods and domains.', 'List the actual software, techniques or certifications you use; show traits through experience statements instead.', confirmation=True)
    else:
        check('skills', 'No skills section requested; neutral credit', True, 1, 'A separate skills section is optional in general mode')

    warnings = [w for w in metadata.get('warnings', []) if w.get('code')!='reconstruction_limited']
    layout_warnings = [w for w in warnings if w['code'] != 'ocr']
    check('readability', 'No detected layout warning', not layout_warnings, .4, '; '.join(w['message'] for w in layout_warnings) or 'No supported layout heuristics flagged a warning; not proof of universal compatibility')
    check('readability', 'No replacement-character extraction damage', '\ufffd' not in text, .2, f"{text.count(chr(65533))} replacement characters")
    check('readability', 'Content is not a single long unbroken paragraph', len(lines) >= 4 or len(words) < 80, .2, f'{len(lines)} nonempty lines')
    check('readability', 'Not predominantly very long lines', not lines or sum(len(line) > 300 for line in lines) <= len(lines) / 2, .2, 'Lines over 300 characters can signal collapsed extraction; this check is a text heuristic')
    for w in warnings:
        issue('readability', 'medium', 'Verify extracted formatting', w['message'], 'Layout detection is limited and varies across ATS products.', 'Compare the preview to your original document, correct reading order, and use a simple single-column layout if needed.')
    if '\ufffd' in text:
        issue('readability', 'critical', 'Extraction contains unreadable characters', 'Replacement character detected in extracted text', 'Damaged extraction may hide essential information.', 'Correct the preview or upload a new PDF/DOCX export.')

    email = re.search(r'\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b', text)
    phone = re.search(r'(?<!\d)(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-])\d{3}[\s.-]\d{4}(?!\d)', text)
    check('contact', 'At least one contact channel', bool(email or phone), .8, email.group() if email else phone.group() if phone else 'No parseable email or phone found')
    top = lines[0] if lines else ''
    check('contact', 'First line provides a nonempty identity/heading', bool(top and not re.fullmatch(r'[\W\d_]+', top)), .2, top[:160] or 'No first line')
    if not (email or phone):
        issue('contact', 'critical', 'No contact channel recognized', 'No parseable email or supported phone pattern in the text', 'Recruiters need a way to contact you. International phone formats may not match this heuristic.', 'Add or correct your actual email address in the contact section, or verify the phone number format in the preview.')
    else:
        strengths.append('A contact channel is visible in extracted text.')

    diagnostics=[]
    date_patterns={'year-month':r'\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])\b','numeric month/year':r'\b(?:0?[1-9]|1[0-2])/(?:19|20)\d{2}\b','named month/year':r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(?:19|20)\d{2}\b'}
    date_evidence={name:re.findall(pattern,text,re.I) for name,pattern in date_patterns.items()};used={name:values for name,values in date_evidence.items() if values}
    diagnostics.append({'key':'consistency','label':'Date & punctuation consistency','status':'review' if len(used)>1 else 'limited checks passed','evidence':'; '.join(name+': '+', '.join(values[:3]) for name,values in used.items()) or 'No supported date patterns detected; dates were not guessed.','scored':False})
    if len(used)>1:issue('readability','low','Review mixed date formats','; '.join(name+': '+', '.join(values[:2]) for name,values in used.items()),'Consistent date presentation improves scanning; this heuristic does not infer incorrect employment dates.','Choose one date format and verify the actual dates. This supplemental warning does not deduct extra points.')
    bullet_lines=[line for line in lines if re.match(r'^[•\-]\s',line)]
    if len(bullet_lines)>=3 and any(line.endswith('.') for line in bullet_lines) and any(not line.endswith('.') for line in bullet_lines):issue('readability','low','Bullet punctuation is inconsistent',' | '.join(bullet_lines[:3])[:500],'Consistent punctuation helps readers follow parallel statements.','Use a consistent bullet punctuation style. This is supplemental advice, not an extra numerical penalty.')
    metric_lines=[line for line in evidence_lines if re.search(r'\d+\s*(?:%|percent|users|hours|clients|projects)',line,re.I)]
    diagnostics.append({'key':'achievement-specificity','label':'Achievement specificity','status':'evidence found' if metric_lines else 'qualitative review recommended','evidence':metric_lines[0][:400] if metric_lines else 'No tracked outcome metric detected. Qualitative impact is valid; no new facts or figures should be invented.','scored':False})
    diagnostics.append({'key':'completeness','label':'Section completeness','status':'review' if any(not value for value in sections.values()) else 'recognized content present','evidence':', '.join(name.title() for name in sections) or 'No exact standard section headings recognized. Custom headings may still be valid.','scored':False})
    diagnostics.append({'key':'grammar','label':'Grammar & semantic accuracy','status':'not deterministically verified','evidence':'Local checks cannot prove grammar or qualifications. Optional consented AI feedback is separate and must be reviewed.','scored':False})

    categories = []
    for key, maximum in weights.items():
        credit = sum(c['fraction'] * c.get('credit_ratio', float(c['passed'])) for c in checks[key])
        score = min(maximum, max(0, int(maximum * credit + .5)))
        label = LABELS[key]
        if mode == 'job' and key == 'keywords':
            label = 'Job-description term relevance'
        if mode == 'job' and key == 'skills':
            label = 'Explicit skills alignment'
        categories.append(Category(key=key, label=label, score=score, maximum=maximum, explanation='; '.join(c['evidence'] for c in checks[key]), checks=checks[key]).model_dump())
    total = sum(c['score'] for c in categories)
    interpretation = 'Strong compatibility' if total >= 90 else 'Good compatibility with improvement opportunities' if total >= 75 else 'Several areas need improvement' if total >= 60 else 'Significant improvements recommended'
    order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    findings.sort(key=lambda f: order[f['priority']])
    return {'overall_score': total, 'categories': categories, 'diagnostics':diagnostics, 'findings': findings, 'strengths': strengths, 'keywords': kw, 'mode': mode, 'interpretation': interpretation, 'scoring_version': version, 'word_count': len(words), 'analyzed_text':text, 'extraction': metadata, 'limitations': ['This internal rubric estimates resume readability and visibility. It is not a validated simulation of every employer ATS and does not guarantee interviews, selection, or employment.', 'Local semantic-quality proxies are limited. AI feedback, when explicitly enabled, is separate from numerical scores.', 'Keyword absence is not proof of missing experience. Confirm all suggested skills before adding them; avoid keyword stuffing.', 'Font, column and document-layout detection is partial. Text boxes, dates, diagrams and decorative elements are not comprehensively assessed.', 'Optional degrees, certifications, phone numbers and measurable outcomes are not mandatory. Supplemental diagnostics are not double-counted; scores are not calibrated for candidate ranking.']}
