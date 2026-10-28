"""Column-aware PDF reading order used by extraction and editable recreation.

Synthetic PDFs are built with PyMuPDF (no browser) so the geometry is exact; one
round-trip test uses the real Chromium export for every gallery template.
"""
import asyncio
import re
from pathlib import Path

import pymupdf
import pytest

from app.document_renderer import browser_path, render_pdf
from app.editor_content import plain_text
from app.extraction import extract
from app.resume_import import clean_title
from app.scoring import heading_key
from app.studio_api import sample_content
from app.templates import TEMPLATES


def write(path: Path, doc):
    path.write_bytes(doc.tobytes())
    return path


def sidebar_pdf(path):
    """Left skills sidebar beside a main experience column (no backgrounds)."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((40, 60), 'Priya Nair', fontsize=24, fontname='hebo')
    page.insert_text((40, 80), 'priya.nair@example.com  |  +44 20 7946 0958', fontsize=9)
    left = [('SKILLS', ['Python, R, SQL,', 'scikit-learn, PyTorch,', 'Airflow, dbt']), ('EDUCATION', ['M.Sc. Data Science', 'University of Leeds, 2019'])]
    right = [('SUMMARY', ['Machine learning engineer focused on forecasting and', 'recommendation systems for e-commerce platforms.']),
             ('EXPERIENCE', ['ML Engineer, Cartwheel Commerce, 2020 - Present', '\u2022 Shipped a demand forecasting model that reduced', '   stockouts by 12% across 3 warehouses.', '\u2022 Built feature pipelines in Airflow and dbt.', 'Data Scientist, Kite Analytics, 2019 - 2020', '\u2022 Prototyped churn models in scikit-learn.'])]
    for column, x in [(left, 40), (right, 220)]:
        y = 120
        for heading, lines in column:
            page.insert_text((x, y), heading, fontsize=11, fontname='hebo')
            y += 16
            for line in lines:
                if line.startswith('\u2022'):
                    page.insert_text((x, y), '\u2022', fontsize=9.5)
                    page.insert_text((x + 10, y), line[2:], fontsize=9.5)
                elif line.startswith('   '):
                    page.insert_text((x + 10, y), line.strip(), fontsize=9.5)
                else:
                    page.insert_text((x, y), line, fontsize=9.5)
                y += 13
            y += 12
    return write(path, doc)


def single_column_pdf(path, pages=1):
    """Single column with right-aligned dates, page numbers and a running header."""
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page(width=612, height=792)
        y = 60
        if number == 1:
            page.insert_text((50, y), 'Jordan Rivera', fontsize=22, fontname='hebo')
            y += 22
            page.insert_text((50, y), 'jordan.rivera@example.com | (555) 201-3344', fontsize=10)
            y += 30
        else:
            page.insert_text((50, 30), 'Jordan Rivera', fontsize=9)
        page.insert_text((50, y), 'EXPERIENCE' if number == 1 else 'EDUCATION', fontsize=12, fontname='hebo')
        y += 18
        for index in range(4):
            title, date = f'Analyst {number}.{index}, Example Org', f'201{index} - 201{index + 1}'
            page.insert_text((50, y), title, fontsize=10.5, fontname='hebo')
            page.insert_text((562 - pymupdf.get_text_length(date, fontsize=10), y), date, fontsize=10)
            y += 15
            page.insert_text((68, y), f'Analyzed operational data for team {number}{index} using SQL.', fontsize=10)
            y += 20
        page.insert_text((300, 770), f'{number} / {pages}', fontsize=9)
    return write(path, doc)


def test_heading_key_accepts_numbered_and_decorated_headings():
    assert heading_key('02 Experience') == 'experience'
    assert heading_key('TECHNICAL SKILLS:') == 'skills'
    assert heading_key('II. Education') == 'education'
    assert heading_key('// Projects') == 'projects'
    assert heading_key('Experience in Python and SQL') is None
    assert clean_title('03 TECHNICAL SKILLS') == 'Technical Skills'


def test_sidebar_columns_are_read_one_at_a_time(tmp_path):
    result = extract(sidebar_pdf(tmp_path / 'sidebar.pdf'), 'pdf')
    text = result['text']
    # Left column completes before the right column begins; nothing interleaves.
    assert text.index('Airflow, dbt') < text.index('University of Leeds') < text.index('SUMMARY') < text.index('Prototyped churn')
    assert 'Python, R, SQL, scikit-learn, PyTorch, Airflow, dbt' in text
    assert 'Shipped a demand forecasting model that reduced stockouts by 12% across 3 warehouses.' in text
    assert any(w['code'] == 'columns' for w in result['extraction']['warnings'])
    rebuilt = result['extraction']['reconstruction']
    assert rebuilt['profile']['columns'] == 2 and rebuilt['profile']['layout'] == 'sidebar-left'
    assert rebuilt['profile']['suggested_template'] == 'sidebar-skills'
    sections = {section['title']: section['html'] for section in rebuilt['content']['sections']}
    assert list(sections) == ['Contact information', 'Skills', 'Education', 'Summary', 'Experience']
    assert '<strong>Priya Nair</strong>' in sections['Contact information']
    assert sections['Experience'].count('<li>') == 3 and sections['Experience'].count('<ul>') == 2
    assert 'Data Scientist, Kite Analytics' in plain_text(sections['Experience']).split('\u2022')[2]


def test_single_column_dates_page_numbers_and_running_headers(tmp_path):
    result = extract(single_column_pdf(tmp_path / 'single.pdf', pages=2), 'pdf')
    text = result['text']
    assert not any(w['code'] == 'columns' for w in result['extraction']['warnings'])
    assert 'Analyst 1.0, Example Org \u00b7 2010 - 2011' in text  # date stays on its entry row
    assert '1 / 2' not in text and '2 / 2' not in text
    assert text.count('Jordan Rivera') == 1  # page-two running header removed
    assert set(result['extraction']['removed_artifacts']) == {'1 / 2', '2 / 2', 'Jordan Rivera'}
    rebuilt = result['extraction']['reconstruction']
    assert rebuilt['profile']['columns'] == 1
    assert [s['title'] for s in rebuilt['content']['sections']] == ['Contact information', 'Experience', 'Education']


def test_reconstruction_never_drops_extracted_tokens(tmp_path):
    result = extract(sidebar_pdf(tmp_path / 'sidebar.pdf'), 'pdf')
    content = result['extraction']['reconstruction']['content']
    rebuilt = ' '.join(section['title'] + ' ' + plain_text(section['html']) for section in content['sections']).lower()
    for token in re.findall(r'\w+', result['text'].lower()):
        assert token in rebuilt


@pytest.mark.skipif(not browser_path(), reason='Chromium/Chrome is required for actual template exports')
def test_every_template_export_round_trips_section_text(tmp_path):
    def normalized(html):
        return re.sub(r'\s+', ' ', plain_text(html).replace('\u2022', '')).strip()
    expected = {section.title.lower(): normalized(section.html) for section in sample_content().sections}
    for template in TEMPLATES:
        content = sample_content()
        content.template = template
        data, _ = asyncio.run(render_pdf(content))
        path = tmp_path / f'{template}.pdf'
        path.write_bytes(data)
        rebuilt = extract(path, 'pdf')['extraction']['reconstruction']['content']['sections']
        got = {section['title'].lower(): normalized(section['html']) for section in rebuilt}
        assert got == expected, template
