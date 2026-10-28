"""Rubric v2 calibration: graded evidence quality and weighted JD terms.

These fixtures are synthetic. The assertions pin relative behaviour (weak < mid <
strong, required terms outweigh preferred ones), not claims about any employer ATS.
"""
from app.ats_terms import extract_terms, present, split_groups
from app.scoring import analyze, is_statement, starts_with_action

WEAK = '''Jordan Lee
jordan@example.com
Experience
Responsible for helping customers. Worked on various tasks for the store team.
Skills
hard worker, team player
'''

MID = '''Jordan Lee
jordan@example.com | 555-201-3344
Summary
Customer-focused retail associate with three years in high-volume stores.
Experience
Sales Associate, Riverside Market, 2021 - Present
- Helped with stocking shelves and worked on the register.
- Responsible for opening the store.
Education
Riverside High School, 2020
Skills
Customer service, cash handling
'''

STRONG = '''Avery Morgan
avery.morgan@example.com | +1 555 010 1020 | Portland, OR
Professional Summary
Backend engineer with 6 years building Python and PostgreSQL services for logistics and payments teams.
Experience
Senior Software Engineer | Northstar Freight | Jan 2021 - Present
- Led migration of 14 billing services from a monolith to FastAPI on Kubernetes, cutting p95 latency by 38%.
- Designed an event-driven reconciliation pipeline in Python and Kafka processing 2M records per day.
- Mentored 4 engineers and introduced code review guidelines adopted across 3 teams.
Software Engineer | Fieldwork Labs | Jun 2018 - Dec 2020
- Built React and TypeScript dashboards used by 250 operations staff to track shipments.
- Automated SQL reporting jobs, saving the finance team roughly 10 hours per week.
Education
B.S. Computer Science | Oregon State University | 2014 - 2018
Technical Skills
Python, TypeScript, React, FastAPI, PostgreSQL, Kafka, Docker, Kubernetes, AWS, Git
Projects
Open Freight Toolkit
- Created an open-source Python library for parsing carrier rate sheets with 300 GitHub stars.
'''

JD = '''Senior Backend Engineer - Payments Platform
Responsibilities:
- Design, build and operate high-throughput microservices in Python or Go.
- Own reliability of payment APIs, including observability, incident response and on-call.
Requirements:
- 5+ years of backend engineering experience.
- Strong experience with PostgreSQL, Kafka and distributed systems.
- Experience with AWS, Terraform and Kubernetes.
- Familiarity with CI/CD pipelines and automated testing.
Nice to have:
- Experience with gRPC and event sourcing.
- Background in fintech or payments.
'''


def category(result, key):
    return next(c for c in result['categories'] if c['key'] == key)


def test_scores_separate_weak_mid_and_strong_resumes():
    weak, mid, strong = (analyze(text, {})['overall_score'] for text in (WEAK, MID, STRONG))
    assert weak < mid < strong
    assert strong - weak >= 35
    assert weak < 60 and strong >= 90


def test_experience_quality_is_graded_not_boolean():
    mid = analyze(MID, {})
    experience = category(mid, 'experience')
    assert 0 < experience['score'] < experience['maximum'] * .6
    verbs = next(c for c in experience['checks'] if 'action verb' in c['label'])
    assert verbs['credit_ratio'] == 0.0 and '0 of 2' in verbs['evidence']
    assert any(f['title'] == 'Lead with what you did' for f in mid['findings'])
    strong = category(analyze(STRONG, {}), 'experience')
    assert strong['score'] == strong['maximum']


def test_generic_traits_do_not_count_as_skills():
    weak = analyze(WEAK, {})
    skills = next(c for c in category(weak, 'skills')['checks'] if 'concrete' in c['label'])
    assert skills['credit_ratio'] == 0.0 and 'hard worker' in skills['evidence']
    assert any(f['category'] == 'skills' for f in weak['findings'])


def test_statement_and_action_helpers():
    assert not is_statement('Senior Software Engineer | Northstar Freight | Jan 2021 - Present')
    assert not is_statement('Jan 2021 - Present')
    assert is_statement('- Built React dashboards for staff')
    assert starts_with_action('- Shipped a forecasting model')
    assert not starts_with_action('- Responsible for opening the store.')


def test_jd_terms_cover_tools_phrases_and_credentials():
    terms, groups = extract_terms(JD, 'Senior Backend Engineer')
    names = {t['term'] for t in terms}
    for expected in ['terraform', 'kafka', 'ci/cd', 'distributed systems', 'go', 'grpc', 'incident response', 'microservices', 'postgresql']:
        assert expected in names, expected
    # Parts of a matched lexicon term are not counted twice.
    assert 'ci' not in names and 'cd' not in names
    weight = {t['term']: t for t in terms}
    assert weight['terraform']['importance'] == 'required'
    assert weight['grpc']['importance'] == 'preferred'
    assert weight['terraform']['weight'] > weight['grpc']['weight']
    assert groups['responsibilities'] and groups['required'] and groups['preferred']


def test_ambiguous_short_terms_need_context():
    assert present('Python, Go, SQL', 'go')
    assert present('Services in Python or Go.', 'go')
    assert not present('Ready to go live with the team.', 'go')
    assert present('Skills: R, SQL, Tableau', 'r')
    assert not present('Our team works hard.', 'r')
    assert present('Postgres and Redis', 'postgresql')


def test_job_mode_weights_required_gaps_and_evidence_placement():
    result = analyze(STRONG, {}, JD, 'job')
    general = analyze(STRONG, {})
    assert result['overall_score'] < general['overall_score']
    kw = result['keywords']
    assert 'terraform' in kw['missing_required'] and 'kafka' in kw['found']
    assert 0 < kw['weighted_coverage'] < 1
    titles = [f['title'] for f in result['findings']]
    assert 'Required job terms are not explicit' in titles
    # A required gap is surfaced ahead of lower-priority findings.
    assert result['findings'][0]['priority'] in ('critical', 'high')
    kafka = next(c for c in kw['contexts'] if c['term'] == 'kafka')
    assert 'experience/projects' in kafka['where']


def test_inline_cues_and_headings_group_clauses():
    groups = split_groups('Required: Python. Preferred: AWS. Responsibilities: build SQL reports.')
    assert groups['required'] == ['Required: Python.']
    assert groups['preferred'] == ['Preferred: AWS.']
    assert groups['responsibilities'] == ['Responsibilities: build SQL reports.']


def test_rubric_version_changed_so_old_results_are_not_compared():
    assert analyze(STRONG, {})['scoring_version'].startswith('local-rubric-2.0-')
