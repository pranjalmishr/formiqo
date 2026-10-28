"""Score records: every saved ATS / job-match analysis as a searchable, exportable table.

The source of truth is the existing ``analyses`` table (one row per real analysis,
owned and expiring with its resume). Nothing is duplicated or recalculated here, so
a record always shows the score exactly as it was computed, with its rubric version.
Exports: CSV (spreadsheet), XLSX (Excel workbook with summary + category sheets)
and JSON (full records including findings and term evidence).
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from .persistence import resume_children
from sqlalchemy.orm import Session as DBSession

from .auth import aware
from .db import Analysis, Resume, get_db, now
from .storage import owner

router = APIRouter(prefix='/api/records', tags=['Score records'])

CATEGORY_KEYS = ['structure', 'keywords', 'experience', 'skills', 'readability', 'contact']
CATEGORY_LABELS = {'structure': 'Structure', 'keywords': 'Keywords / relevance', 'experience': 'Experience', 'skills': 'Skills', 'readability': 'Readability', 'contact': 'Contact'}
COLUMNS = ['analysis_id', 'analyzed_at', 'resume', 'mode', 'job_title', 'company', 'ats_score', 'job_match_score',
           'weighted_term_coverage', 'required_terms_found', 'required_terms_total', 'terms_found', 'terms_total',
           'missing_required_terms', 'interpretation', 'findings', 'high_priority_findings',
           *[f'{key}_score' for key in CATEGORY_KEYS], 'word_count', 'scoring_version', 'resume_id', 'expires_at']


def match_score(result: dict):
    """Job-match score exactly as the matcher reports it (keywords + skills categories)."""
    if result.get('mode') != 'job':
        return None
    if isinstance(result.get('match_score'), int):
        return result['match_score']
    parts = [c for c in result.get('categories', []) if c.get('key') in ('keywords', 'skills')]
    total = sum(c['maximum'] for c in parts)
    return round(sum(c['score'] for c in parts) / total * 100) if total else None


def record(analysis: Analysis, resume: Resume):
    result = analysis.result or {}
    context = result.get('context') or {}
    kw = result.get('keywords') or {}
    categories = {c['key']: c for c in result.get('categories', []) if 'key' in c}
    findings = result.get('findings') or []
    coverage = kw.get('weighted_coverage')
    return {
        'analysis_id': analysis.id,
        'analyzed_at': aware(analysis.created_at).isoformat(),
        'resume': resume.filename,
        'resume_id': resume.id,
        'mode': 'Job match' if result.get('mode') == 'job' else 'General ATS',
        'job_title': context.get('job_title') or '',
        'company': context.get('company') or '',
        'ats_score': analysis.overall_score,
        'job_match_score': match_score(result),
        'weighted_term_coverage': round(coverage * 100) if isinstance(coverage, (int, float)) else None,
        'required_terms_found': kw.get('required_found'),
        'required_terms_total': kw.get('required_total'),
        'terms_found': len(kw.get('found') or []) if result.get('mode') == 'job' else None,
        'terms_total': kw.get('candidate_count') if result.get('mode') == 'job' else None,
        'missing_required_terms': ', '.join(kw.get('missing_required') or []),
        'interpretation': result.get('interpretation', ''),
        'findings': len(findings),
        'high_priority_findings': sum(1 for f in findings if f.get('priority') in ('critical', 'high')),
        **{f'{key}_score': (f"{categories[key]['score']}/{categories[key]['maximum']}" if key in categories else '') for key in CATEGORY_KEYS},
        'word_count': result.get('word_count'),
        'scoring_version': analysis.scoring_version,
        'expires_at': aware(resume.expires_at).isoformat(),
        'categories': [{'key': c['key'], 'label': c.get('label', CATEGORY_LABELS.get(c['key'], c['key'])), 'score': c['score'], 'maximum': c['maximum']} for c in result.get('categories', [])],
    }


def owned_records(db: DBSession, owner_id: str, mode: str, query: str, resume_id: str | None, since: datetime | None):
    rows = [record(a,r) for a,r in resume_children(db,Analysis,owner_id,resume_id=resume_id,since=since)]
    if mode in ('general', 'job'):
        rows = [row for row in rows if (row['mode'] == 'Job match') == (mode == 'job')]
    if query:
        needle = query.lower()
        rows = [row for row in rows if needle in ' '.join(str(row[key]) for key in ('resume', 'job_title', 'company', 'interpretation')).lower()]
    return rows


def summary(rows: list[dict]):
    ats = [row['ats_score'] for row in rows]
    match = [row['job_match_score'] for row in rows if row['job_match_score'] is not None]
    best = max(rows, key=lambda row: row['ats_score'], default=None)
    return {'records': len(rows), 'resumes': len({row['resume_id'] for row in rows}), 'job_matches': len(match),
            'average_ats': round(sum(ats) / len(ats)) if ats else None, 'best_ats': best['ats_score'] if best else None,
            'best_resume': best['resume'] if best else None, 'average_job_match': round(sum(match) / len(match)) if match else None}


@router.get('')
def list_records(mode: Literal['all', 'general', 'job'] = 'all', q: str = Query('', max_length=120), resume_id: str | None = None,
                 since: datetime | None = None, sort: Literal['newest', 'oldest', 'ats', 'match'] = 'newest',
                 offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=200), owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rows = owned_records(db, owner_id, mode, q.strip(), resume_id, since)
    if sort == 'oldest':
        rows.reverse()
    elif sort == 'ats':
        rows.sort(key=lambda row: -row['ats_score'])
    elif sort == 'match':
        rows.sort(key=lambda row: -(row['job_match_score'] if row['job_match_score'] is not None else -1))
    resumes = sorted({(row['resume_id'], row['resume']) for row in owned_records(db, owner_id, 'all', '', None, None)}, key=lambda item: item[1].lower())
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'summary': summary(rows),
            'resumes': [{'id': rid, 'filename': name} for rid, name in resumes],
            'notice': 'Records are your saved analyses, shown exactly as scored. They expire with their resume; download them to keep a copy.'}


def csv_bytes(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Neutralize spreadsheet formula injection from user-controlled text cells.
        writer.writerow({key: ("'" + value if isinstance(value, str) and value[:1] in ('=', '+', '-', '@') else value) for key, value in row.items()})
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')


def xlsx_bytes(rows, overview):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    book = Workbook()
    sheet = book.active
    sheet.title = 'Score records'
    header_font, fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='4A52A3')
    titles = [column.replace('_', ' ').title() for column in COLUMNS]
    sheet.append(titles)
    for cell in sheet[1]:
        cell.font, cell.fill, cell.alignment = header_font, fill, Alignment(vertical='center')
    for row in rows:
        values = []
        for key in COLUMNS:
            value = row.get(key)
            if key in ('analyzed_at', 'expires_at') and value:
                value = datetime.fromisoformat(value).replace(tzinfo=None)
            if isinstance(value, str) and value[:1] in ('=', '+', '-', '@'):
                value = "'" + value
            values.append(value)
        sheet.append(values)
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for index, key in enumerate(COLUMNS, start=1):
        width = 14 if key.endswith('_score') or key.endswith('_id') is False and len(key) < 12 else 20
        if key in ('resume', 'missing_required_terms', 'interpretation'):
            width = 34
        sheet.column_dimensions[get_column_letter(index)].width = width
        if key in ('analyzed_at', 'expires_at'):
            for cell in sheet[get_column_letter(index)][1:]:
                cell.number_format = 'yyyy-mm-dd hh:mm'
    summary_sheet = book.create_sheet('Summary')
    for label, value in [('Records', overview['records']), ('Resumes', overview['resumes']), ('Average ATS score', overview['average_ats']),
                         ('Best ATS score', overview['best_ats']), ('Best resume', overview['best_resume']), ('Job matches', overview['job_matches']),
                         ('Average job-match score', overview['average_job_match']), ('Exported at (UTC)', now().replace(tzinfo=None))]:
        summary_sheet.append([label, value])
    summary_sheet.column_dimensions['A'].width = 26
    summary_sheet.column_dimensions['B'].width = 40
    for cell in summary_sheet['A']:
        cell.font = Font(bold=True)
    summary_sheet['B8'].number_format = 'yyyy-mm-dd hh:mm'
    note = book.create_sheet('About')
    note.append(['Scores are internal rubric estimates (not employer ATS results). Job-match score = keywords + skills categories. Rubric versions differ; compare only records with the same scoring version.'])
    note.column_dimensions['A'].width = 140
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@router.get('/export')
def export_records(format: Literal['csv', 'xlsx', 'json'] = 'csv', mode: Literal['all', 'general', 'job'] = 'all', q: str = Query('', max_length=120),
                   resume_id: str | None = None, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    rows = owned_records(db, owner_id, mode, q.strip(), resume_id, None)
    if not rows:
        raise HTTPException(404, 'No score records match these filters yet. Run an ATS check or job match first.')
    stamp = now().strftime('%Y%m%d-%H%M')
    if format == 'csv':
        return Response(csv_bytes(rows), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="formiqo-score-records-{stamp}.csv"'})
    if format == 'xlsx':
        return Response(xlsx_bytes(rows, summary(rows)), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="formiqo-score-records-{stamp}.xlsx"'})
    full = []
    by_id = {row['analysis_id']:db.get(Analysis,row['analysis_id']) for row in rows}
    for row in rows:
        result = by_id[row['analysis_id']].result or {}
        full.append({**row, 'findings_detail': result.get('findings', []), 'strengths': result.get('strengths', []),
                     'keyword_terms': (result.get('keywords') or {}).get('contexts', []), 'job_description': (result.get('context') or {}).get('job_description', '')})
    body = json.dumps({'exported_at': now().isoformat(), 'summary': summary(rows), 'records': full}, indent=2, ensure_ascii=False)
    return Response(body.encode('utf-8'), media_type='application/json', headers={'Content-Disposition': f'attachment; filename="formiqo-score-records-{stamp}.json"'})


@router.delete('/{analysis_id}', status_code=204)
def delete_record(analysis_id: str, owner_id=Depends(owner), db: DBSession = Depends(get_db)):
    analysis = db.get(Analysis, analysis_id)
    if not analysis or analysis.owner != owner_id:
        raise HTTPException(404, 'Record not found.')
    db.delete(analysis)
    db.commit()
    return Response(status_code=204)
