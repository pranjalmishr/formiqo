"""Job-description term extraction for the transparent ATS rubric.

Terms come from three published sources, never from an opaque model:

1. A curated lexicon of skills, tools, methods and credentials (with aliases, so
   "Postgres" matches "PostgreSQL" and "CI/CD" matches "continuous integration").
2. Capitalized or symbol-bearing technical tokens in the JD (gRPC, Terraform, C#).
3. Repeated multi-word noun phrases ("distributed systems", "incident response").

Each term is weighted by where it appears: required > responsibilities > preferred,
plus repetition and title presence. Weights are reported with the evidence.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# canonical term -> aliases (lowercase). Aliases are matched as whole terms.
LEXICON: dict[str, list[str]] = {
    # languages
    'python': [], 'java': [], 'javascript': ['js'], 'typescript': ['ts'], 'go': ['golang'], 'rust': [], 'c++': ['cpp'], 'c#': ['csharp', '.net c#'],
    'ruby': [], 'php': [], 'kotlin': [], 'swift': [], 'scala': [], 'r': [], 'sql': [], 'bash': ['shell scripting'], 'matlab': [],
    # web / frameworks
    'react': ['react.js', 'reactjs'], 'angular': [], 'vue': ['vue.js'], 'next.js': ['nextjs'], 'node.js': ['nodejs', 'node'], 'django': [], 'flask': [],
    'fastapi': [], 'spring': ['spring boot'], 'rails': ['ruby on rails'], '.net': ['dotnet', 'asp.net'], 'graphql': [], 'rest': ['restful', 'rest api', 'rest apis'],
    'grpc': [], 'apis': ['api'], 'html': ['html5'], 'css': ['css3'], 'tailwind': ['tailwind css'],
    # data / ml
    'postgresql': ['postgres'], 'mysql': [], 'mongodb': ['mongo'], 'redis': [], 'elasticsearch': [], 'kafka': ['apache kafka'], 'spark': ['apache spark', 'pyspark'],
    'airflow': ['apache airflow'], 'dbt': [], 'snowflake': [], 'bigquery': [], 'pandas': [], 'numpy': [], 'scikit-learn': ['sklearn'], 'pytorch': [],
    'tensorflow': [], 'machine learning': ['ml'], 'deep learning': [], 'nlp': ['natural language processing'], 'computer vision': [], 'llm': ['llms', 'large language models'],
    'data analysis': ['data analytics'], 'data science': [], 'data modeling': ['data modelling'], 'etl': ['elt', 'data pipelines'], 'statistics': ['statistical analysis'],
    'a/b testing': ['ab testing', 'experimentation'], 'tableau': [], 'power bi': ['powerbi'], 'looker': [], 'excel': ['microsoft excel'],
    # cloud / infra
    'aws': ['amazon web services'], 'azure': ['microsoft azure'], 'gcp': ['google cloud', 'google cloud platform'], 'docker': ['containers'], 'kubernetes': ['k8s'],
    'terraform': [], 'ansible': [], 'linux': [], 'ci/cd': ['continuous integration', 'continuous delivery', 'continuous deployment', 'cicd'], 'github actions': [], 'jenkins': [],
    'git': ['github', 'gitlab'], 'microservices': ['microservice'], 'distributed systems': [], 'serverless': ['lambda'], 'observability': ['monitoring'],
    'prometheus': [], 'grafana': [], 'datadog': [], 'security': ['application security', 'appsec'], 'networking': [],
    # practices
    'agile': [], 'scrum': [], 'kanban': [], 'jira': [], 'automated testing': ['test automation', 'unit testing', 'integration testing'], 'tdd': ['test-driven development'],
    'code review': ['code reviews'], 'system design': [], 'api design': [], 'accessibility': ['wcag', 'a11y'], 'incident response': ['on-call', 'on call'],
    'event-driven architecture': ['event-driven', 'event sourcing'],
    # design / product / business
    'figma': [], 'ux': ['user experience', 'ux design'], 'ui': ['user interface', 'ui design'], 'user research': [], 'prototyping': [], 'product management': [],
    'project management': [], 'stakeholder management': ['stakeholders'], 'roadmap': ['roadmaps', 'roadmapping'], 'seo': [], 'sem': [], 'content marketing': [],
    'marketing': [], 'crm': [], 'salesforce': [], 'hubspot': [], 'sales': [], 'business development': [], 'customer service': ['customer support'],
    'accounting': [], 'financial modeling': ['financial modelling'], 'budgeting': ['budgets'], 'forecasting': [], 'sap': [], 'quickbooks': [],
    'leadership': ['led teams', 'team leadership'], 'mentoring': ['mentorship', 'mentored'], 'communication': ['communication skills'], 'cross-functional': ['cross functional'],
    # engineering / healthcare / ops
    'cad': ['autocad', 'solidworks'], 'plc': [], 'six sigma': ['lean six sigma'], 'lean': [], 'quality assurance': ['qa'], 'gmp': [], 'hipaa': [], 'epic': [], 'ehr': ['emr'],
    'patient care': [], 'supply chain': [], 'logistics': [], 'inventory management': [], 'procurement': [],
    # credentials / compliance
    'pci dss': ['pci', 'pci-dss'], 'soc 2': ['soc2'], 'gdpr': [], 'iso 27001': [], 'pmp': [], 'cpa': [], 'cfa': [], 'aws certified': [], 'cissp': [],
}

# Single-letter or ambiguous aliases must appear in a skills-like context to count.
AMBIGUOUS = {'r', 'go', 'js', 'ts', 'node', 'ml', 'qa', 'lean', 'epic', 'rest', 'ui', 'ux', 'lambda', 'containers', 'monitoring', 'stakeholders', 'sales', 'marketing', 'security', 'pci'}

STOP = set('''the and for with that this from your you our are will have has can not all their they into work role team candidate required requirements preferred
qualifications experience knowledge ability skills strong excellent including using must years year job responsibilities seeking company about also such demonstrate
demonstrated proficiency understanding bachelor bachelors degree minimum plus least related field relevant position working support develop development looking good new
more one within provide through opportunity candidates hiring or of to in on a an is as be by at it we us do if who what when where how why which while than then them
its other others any each every both few many most some such only own same so too very just over under again further once here there across per via etc ideal ideally
nice bonus able well highly great join help make build built ensure drive across based like including include includes day days week weeks environment culture
benefits salary apply applicants equal employer opportunity people world mission'''.split())

GENERIC_PHRASE_WORDS = STOP | set('''best fast paced passionate self starter motivated detail oriented attention ability work hard player
senior junior lead staff principal intern entry mid level'''.split())

# Ambiguous short terms count only in their conventional capitalization, mid-sentence
# ("Python or Go", "R and SQL"), or inside a comma/bullet-separated list.
DISPLAY = {'go': 'Go', 'r': 'R', 'js': 'JS', 'ts': 'TS', 'ml': 'ML', 'qa': 'QA', 'ui': 'UI', 'ux': 'UX', 'rest': 'REST', 'epic': 'Epic', 'lean': 'Lean', 'pci': 'PCI', 'node': 'Node'}

TECH_TOKEN = re.compile(r'(?<![\w/])(?:[A-Z][a-z]+[A-Z][A-Za-z]*|[A-Z]{2,}[a-z]*|[A-Za-z]+(?:\.js|\.NET|#|\+\+)|[a-z]+[A-Z][A-Za-z]+)(?![\w])')
GROUP_PATTERNS = [
    ('preferred', re.compile(r'\b(?:preferred|nice[ -]to[ -]haves?|bonus|a plus|desirable|ideally)\b', re.I)),
    ('required', re.compile(r'\b(?:must|required|requirements?|minimum|qualifications?|what you(?:\'ll| will)? (?:need|bring)|you have|you bring)\b', re.I)),
    ('responsibilities', re.compile(r'\b(?:responsibilit\w*|duties|what you(?:\'ll| will) do|you will|day[- ]to[- ]day|in this role)\b', re.I)),
]
GROUP_WEIGHT = {'required': 3.0, 'responsibilities': 2.0, 'preferred': 1.0, 'general': 1.5}


def term_pattern(term: str):
    return re.compile(r'(?<![\w+#./-])' + re.escape(term) + r'(?![\w+#]|\.[a-z])', re.I)


def contains(text: str, term: str):
    return bool(term_pattern(term).search(text))


def variants(term: str):
    return [term] + LEXICON.get(term, [])


def present(text: str, term: str):
    """Return the first matching variant, or None. Ambiguous aliases need list context."""
    for variant in variants(term):
        if variant in AMBIGUOUS:
            listed = re.compile(r'(?:^|[,|\u2022\u00b7:;/(]\s*)' + re.escape(variant) + r'(?=\s*(?:[,|\u00b7;/)]|$))', re.I | re.M)
            display = DISPLAY.get(variant)
            styled = display and re.search(r'(?<![.!?]\s)(?<!^)(?<![\w+#./-])' + re.escape(display) + r'(?![\w+#-])', text, re.M)
            if listed.search(text) or styled:
                return variant
            continue
        if contains(text, variant):
            return variant
    return None


def split_groups(jd: str):
    """Assign each JD clause to required / preferred / responsibilities / general.

    A heading line switches the current group; an inline cue changes only its clause.
    """
    groups: dict[str, list[str]] = {'required': [], 'preferred': [], 'responsibilities': [], 'general': []}
    current = 'general'
    clauses = re.split(r'\n|(?<=[.;])\s+|\s+(?=(?:Required|Preferred|Responsibilities|Requirements|Qualifications)\s*:)', jd)
    for raw in clauses:
        line = raw.strip(' \t-\u2022*')
        if not line:
            continue
        cue = next((name for name, pattern in GROUP_PATTERNS if pattern.search(line)), None)
        heading = len(line) <= 60 and (line.endswith(':') or (cue and len(line.split()) <= 6))
        if heading and cue:
            current = cue
        groups[cue if cue and not heading else current].append(line[:500])
    return groups


def _phrases(jd: str):
    """Repeated 2-3 word content phrases, e.g. 'payment apis', 'incident response'."""
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z+#./-]*", jd)]
    counts = Counter()
    for size in (2, 3):
        for index in range(len(words) - size + 1):
            gram = words[index:index + size]
            if any(w in GENERIC_PHRASE_WORDS or len(w) < 3 for w in gram):
                continue
            counts[' '.join(gram)] += 1
    return [phrase for phrase, count in counts.most_common() if count >= 2]


def extract_terms(jd: str, title: str = ''):
    """Weighted candidate terms with their JD contexts."""
    groups = split_groups(jd)
    found: dict[str, dict] = {}

    def add(term, kind):
        term = term.strip().lower()
        if not term or term in STOP or len(term) > 40:
            return
        if term not in found:
            found[term] = {'term': term, 'kind': kind, 'contexts': [], 'groups': set(), 'mentions': 0}

    for term in LEXICON:
        if present(jd, term):
            add(term, 'skill or tool')
    covered = {v for term in found for v in variants(term)}
    # Mask lexicon matches so their parts ("CI" of CI/CD, "DSS" of PCI DSS) are not re-counted.
    masked = jd
    for variant in sorted(covered, key=len, reverse=True):
        masked = term_pattern(variant).sub(' ', masked)
    for token in TECH_TOKEN.findall(masked):
        value = token.lower()
        if value in covered or value in STOP or len(value) < 2 or value.isdigit():
            continue
        if any(value in variants(term) for term in LEXICON):
            continue
        # Skip sentence-initial ordinary words ("We", "Our") and acronym noise.
        if token[0].isupper() and token[1:].islower():
            continue
        add(value, 'technical term')
    for phrase in _phrases(masked):
        if any(phrase in v or v in phrase for term in found for v in variants(term)):
            continue
        add(phrase, 'repeated job phrase')
    # Repeated single content words as a last, lower-weight source.
    counts = Counter(w.lower() for w in re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', jd) if w.lower() not in STOP)
    for word, count in counts.most_common(40):
        if count >= 3 and not any(word in t.split() for t in found):
            add(word, 'repeated job word')

    lowered_title = title.lower()
    for term, record in found.items():
        for name, lines in groups.items():
            for line in lines:
                if present(line, term) or contains(line, term):
                    record['groups'].add(name)
                    record['mentions'] += 1
                    if len(record['contexts']) < 4:
                        record['contexts'].append({'group': name, 'excerpt': line})
        record['mentions'] = max(1, record['mentions'])
        group_weight = max((GROUP_WEIGHT[g] for g in record['groups']), default=GROUP_WEIGHT['general'])
        weight = group_weight + min(1.5, .5 * (record['mentions'] - 1)) + (1.0 if lowered_title and contains(lowered_title, term) else 0)
        if record['kind'] == 'repeated job word':
            weight *= .5
        record['weight'] = round(weight, 2)
        record['importance'] = 'required' if 'required' in record['groups'] else 'preferred' if record['groups'] == {'preferred'} else 'core' if record['groups'] & {'responsibilities'} else 'mentioned'
        record['groups'] = sorted(record['groups'])
    ordered = sorted(found.values(), key=lambda r: (-r['weight'], r['term']))[:40]
    return ordered, groups


def match_terms(jd: str, resume_text: str, sections: dict[str, list[str]] | None = None, title: str = ''):
    """Weighted JD coverage. A missing term is a visibility gap, not a missing skill."""
    terms, groups = extract_terms(jd, title)
    sections = sections or {}
    evidence_text = '\n'.join(sections.get('experience', []) + sections.get('projects', []))
    skills_text = '\n'.join(sections.get('skills', []))
    for record in terms:
        variant = present(resume_text, record['term'])
        record['present'] = variant is not None
        record['matched_as'] = variant
        record['requires_confirmation'] = variant is None
        if variant is None:
            record['where'] = []
        else:
            where = []
            if evidence_text and present(evidence_text, record['term']):
                where.append('experience/projects')
            if skills_text and present(skills_text, record['term']):
                where.append('skills')
            record['where'] = where or ['elsewhere']
    total = sum(r['weight'] for r in terms) or 1
    covered = sum(r['weight'] for r in terms if r['present'])
    in_evidence = sum(r['weight'] for r in terms if r['present'] and 'experience/projects' in r['where'])
    required = [r for r in terms if r['importance'] == 'required']
    return {
        'terms': terms,
        'groups': groups,
        'weighted_coverage': round(covered / total, 4),
        'evidence_coverage': round(in_evidence / max(covered, 1e-9), 4) if covered else 0.0,
        'required_total': len(required),
        'required_found': sum(1 for r in required if r['present']),
    }
