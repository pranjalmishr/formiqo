"""Column-aware reading order for selectable-text PDF resumes.

Resumes often use sidebars or two columns. Sorting lines top-to-bottom across the
whole page (PyMuPDF ``sort=True``) interleaves those columns, so a heading collects
text from the neighbouring column. This module:

* detects a vertical gutter from line geometry (validated so right-aligned dates in a
  single-column resume are not mistaken for a column),
* reads full-width bands top to bottom and column bands column by column,
* merges same-row fragments (skill tags, split spans) and rejoins wrapped lines into
  paragraphs and list items (text bullets or small vector bullet markers),
* removes page-number lines and running headers repeated on later pages, and reports
  every removal.

It only reorders and joins text from the PDF text layer; it never invents content.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from html import escape
from statistics import median
from typing import Callable

BULLET_PREFIX = re.compile(r'^\s*(?:[\u2022\u25cf\u25aa\u25a0\u25e6\u25cb\u2023\u2043\u2219\u27a2\u25ba\u2713\u2714*]|[-\u2013\u2014](?=\s))\s*')
BULLET_ONLY = re.compile(r'^\s*[\u2022\u25cf\u25aa\u25a0\u25e6\u25cb\u2023\u2043\u2219\u27a2\u25ba\u2713\u2714*\-\u2013\u2014]\s*$')
PAGE_NUMBER = re.compile(r'(?:page\s*)?\d{1,3}(?:\s*(?:/|of)\s*\d{1,3})?', re.I)
# A middle dot starts a list item only when the line is not a visible continuation
# ("Accessibility Foundations / \u00b7 Example Institute" is one wrapped entry).
SOFT_BULLET = re.compile(r'^\s*[\u00b7\u2024]\s+(?=\S)')
CONTINUES = re.compile(r'(?:[,\u00b7|&/+;:]|\band|\bor|\bwith|\bthe|\bof|\bfor|\bto|\bin)$', re.I)
CAPS_HEADING = re.compile(r"[A-Z][A-Z &/'\-]{2,38}")
MAX_DRAWINGS = 4000


@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    html: str
    size: float
    page: int = 0
    bullet: bool = False
    column: str = 'full'
    glyph: bool = False  # bullet character was part of this line's own text

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2

    @property
    def height(self):
        return max(1.0, self.y1 - self.y0)

    @property
    def width(self):
        return self.x1 - self.x0


@dataclass
class Paragraph:
    text: str
    html: str
    size: float
    page: int
    column: str
    bullet: bool
    x0: float
    y0: float


@dataclass
class PageLayout:
    number: int
    width: float
    height: float
    paragraphs: list[Paragraph] = field(default_factory=list)
    columns: int = 1
    gutter: float | None = None
    left_share: float | None = None
    sidebar_fill: str | None = None
    sidebar_side: str | None = None
    removed: list[str] = field(default_factory=list)

    def text(self):
        return '\n'.join(('\u2022 ' if p.bullet else '') + p.text for p in self.paragraphs)


def _is_bold(span):
    font = (span.get('font') or '').lower()
    return bool(span.get('flags', 0) & 16) or any(key in font for key in ('bold', 'black', 'heavy', 'semibold', 'demi'))


def _is_italic(span):
    font = (span.get('font') or '').lower()
    return bool(span.get('flags', 0) & 2) or 'italic' in font or 'oblique' in font


def _runs_html(runs):
    """Merge adjacent runs with equal emphasis and return safe inline HTML."""
    merged = []
    for text, bold, italic in runs:
        if merged and merged[-1][1] == bold and merged[-1][2] == italic:
            merged[-1][0] += text
        else:
            merged.append([text, bold, italic])
    out = []
    for text, bold, italic in merged:
        token = escape(text)
        if not token:
            continue
        if italic:
            token = '<em>' + token + '</em>'
        if bold and text.strip():
            token = '<strong>' + token + '</strong>'
        out.append(token)
    return ''.join(out)


def _line_from_spans(spans, bbox, page_number):
    runs = [(span.get('text', ''), _is_bold(span), _is_italic(span)) for span in spans]
    text = ''.join(run[0] for run in runs)
    bullet = False
    match = BULLET_PREFIX.match(text)
    if match and match.end() < len(text):
        bullet = True
        remove = match.end()
        trimmed = []
        for value, bold, italic in runs:
            if remove >= len(value):
                remove -= len(value)
                continue
            trimmed.append((value[remove:], bold, italic))
            remove = 0
        runs = trimmed
        text = ''.join(run[0] for run in runs)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return None
    runs = [(re.sub(r'\s+', ' ', value), bold, italic) for value, bold, italic in runs]
    sizes = [span.get('size', 10.0) for span in spans if span.get('text', '').strip()] or [10.0]
    html = _runs_html(runs).strip()
    return Line(*bbox, text=text, html=html, size=round(max(sizes), 2), page=page_number, bullet=bullet, glyph=bullet)


def _markers(page, width, height):
    """Small filled vector shapes used as list bullets, plus a tall sidebar background."""
    markers, sidebar = [], None
    try:
        drawings = page.get_drawings()
    except Exception:
        return markers, sidebar
    if len(drawings) > MAX_DRAWINGS:
        return markers, sidebar
    for drawing in drawings:
        rect, fill = drawing.get('rect'), drawing.get('fill')
        if rect is None or fill is None:
            continue
        w, h = rect.width, rect.height
        if 1.5 <= w <= 7 and 1.5 <= h <= 7:
            markers.append(((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2))
        elif h >= .5 * height and .12 * width <= w <= .5 * width and sum(fill[:3]) < 2.7:
            color = '#' + ''.join(format(int(max(0, min(1, value)) * 255), '02x') for value in fill[:3])
            side = 'left' if (rect.x0 + rect.x1) / 2 < width / 2 else 'right'
            if sidebar is None or w * h > sidebar[2]:
                sidebar = (color, side, w * h)
    return markers, sidebar


def page_lines(page, page_number):
    width, height = page.rect.width, page.rect.height
    lines, removed, glyph_markers = [], [], []
    for block in page.get_text('dict')['blocks']:
        if block.get('type') != 0:
            continue
        for raw in block.get('lines', []):
            spans = [span for span in raw.get('spans', []) if span.get('text')]
            if not spans:
                continue
            joined = ''.join(span['text'] for span in spans)
            x0, y0, x1, y1 = raw['bbox']
            if BULLET_ONLY.match(joined):
                glyph_markers.append(((x0 + x1) / 2, (y0 + y1) / 2))
                continue
            line = _line_from_spans(spans, raw['bbox'], page_number)
            if not line:
                continue
            edge = line.y1 < height * .07 or line.y0 > height * .92
            if edge and PAGE_NUMBER.fullmatch(line.text):
                removed.append(line.text)
                continue
            if len(line.text) <= 2 and not re.search(r'\w', line.text):
                # Decorative glyphs such as a code-style prompt marker.
                removed.append(line.text)
                continue
            lines.append(line)
    markers, sidebar = _markers(page, width, height)
    for mx, my in markers + glyph_markers:
        candidates = [line for line in lines if mx < line.x0 <= mx + 26 and abs(line.yc - my) <= max(3.0, .55 * line.height)]
        if candidates:
            min(candidates, key=lambda line: line.x0 - mx).bullet = True
    return lines, removed, sidebar


def _merge_rows(lines, is_heading=lambda text: False):
    """Join fragments sharing a baseline within one column (e.g. skill tags).

    A section heading is never merged with its neighbour: label-rail layouts put
    the heading on the same baseline as the first entry.
    """
    ordered = sorted(lines, key=lambda line: (round(line.yc, 1), line.x0))
    rows = []
    for line in ordered:
        if is_heading(line.text):
            rows.append([line])
            continue
        # Similar type size only: a large name beside small contact text is two rows.
        # Same baseline (not merely touching boxes on tightly leaded lines) and beside the row.
        row = next((r for r in rows[-4:] if r[0].column == line.column and not is_heading(r[0].text) and abs(r[-1].size - line.size) <= 1.5 and min(r[-1].y1, line.y1) - max(r[-1].y0, line.y0) >= .6 * min(r[-1].height, line.height) and abs(r[-1].y1 - line.y1) <= .35 * line.height and line.x0 >= max(m.x1 for m in r) - 1), None)
        if row is not None and not line.bullet:
            row.append(line)
        else:
            rows.append([line])
    rows = _join_wrapped_cells(rows)
    merged = []
    for row in rows:
        row.sort(key=lambda line: line.x0)
        first = row[0]
        if len(row) == 1:
            merged.append(first)
            continue
        text, html = first.text, first.html
        for previous, line in zip(row, row[1:]):
            gap = line.x0 - previous.x1
            separator = ' \u00b7 ' if gap > 2.5 * line.size and not CONTINUES.search(text) else ' '
            text += separator + line.text
            html += escape(separator) + line.html
        merged.append(Line(first.x0, min(l.y0 for l in row), max(l.x1 for l in row), max(l.y1 for l in row), text, html, max(l.size for l in row), first.page, first.bullet, first.column, first.glyph))
    return merged


def _join_wrapped_cells(rows):
    """Grid cells (skill tags) whose text wraps to a second line are joined per cell.

    Without this, row-major merging reads "Automated Product / testing, collaboration"
    for two wrapped cells. A lower row continues the upper one only when every lower
    fragment sits directly under an upper fragment and an upper fragment does not end
    with a list separator.
    """
    result = []
    for row in rows:
        # Rows from the other column interleave in y order; compare within one column.
        position = next((index for index in range(len(result) - 1, -1, -1) if result[index][0].column == row[0].column), None)
        previous = result[position] if position is not None else None
        if previous and len(row) >= 2 and len(previous) >= 2:
            upper = sorted(previous, key=lambda line: line.x0)
            lower = sorted(row, key=lambda line: line.x0)
            gap = min(line.y0 for line in lower) - max(line.y1 for line in upper)
            pairs = [(next((u for u in upper if abs(u.x0 - l.x0) <= 2.5), None), l) for l in lower]
            open_cell = any(not re.search(r'[,;\u00b7|]$', u.text) for u, _ in pairs if u is not None)
            if all(u is not None for u, _ in pairs) and 0 <= gap <= 1.2 * lower[0].size and open_cell:
                joined = []
                for u in upper:
                    below = next((l for uu, l in pairs if uu is u), None)
                    if below is None:
                        joined.append(u)
                    else:
                        joined.append(Line(u.x0, u.y0, max(u.x1, below.x1), below.y1, u.text + ' ' + below.text, u.html + ' ' + below.html, max(u.size, below.size), u.page, u.bullet, u.column))
                result[position] = joined
                continue
        result.append(row)
    return result


def reading_sort(lines):
    """Top-to-bottom rows, left-to-right within a row.

    Lines whose vertical extents overlap form one visual row even when their tops
    differ (a 27 pt name beside 9 pt contact text), so the left item reads first.
    """
    rows = []
    for line in sorted(lines, key=lambda line: (line.y0, line.x0)):
        if rows:
            top, bottom, members = rows[-1]
            if min(bottom, line.y1) - max(top, line.y0) >= .5 * min(line.height, min(m.height for m in members)):
                members.append(line)
                rows[-1] = (top, max(bottom, line.y1), members)
                continue
        rows.append((line.y0, line.y1, [line]))
    return [line for _, _, members in rows for line in sorted(members, key=lambda line: line.x0)]


def header_order(lines, width):
    """Identity header order: a split header (identity left, contact right) reads the
    left block before the right block; otherwise rows read left to right."""
    if len(lines) < 2:
        return lines
    mid = width / 2
    left = [line for line in lines if line.x1 <= mid + .05 * width and line.x0 < .35 * width]
    right = [line for line in lines if line.x0 >= mid - .05 * width]
    spanning = [line for line in lines if line not in left and line not in right]
    if left and right and not spanning and len(left) + len(right) == len(lines):
        return reading_sort(left) + reading_sort(right)
    return reading_sort(lines)


def find_gutter(lines, width):
    """Return (left_edge, right_edge) of a validated column gutter, or None."""
    if len(lines) < 8:
        return None
    total_chars = sum(len(line.text) for line in lines) or 1
    content_top, content_bottom = min(l.y0 for l in lines), max(l.y1 for l in lines)
    content_height = max(1.0, content_bottom - content_top)
    best = None
    for step in range(int(width * .18), int(width * .82), 3):
        g = float(step)
        left = [l for l in lines if l.x1 <= g]
        right = [l for l in lines if l.x0 >= g]
        if len(left) < 4 or len(right) < 4:
            continue
        left_chars, right_chars = sum(len(l.text) for l in left), sum(len(l.text) for l in right)
        if left_chars < .12 * total_chars or right_chars < .12 * total_chars:
            continue
        top = max(min(l.y0 for l in left), min(l.y0 for l in right))
        bottom = min(max(l.y1 for l in left), max(l.y1 for l in right))
        if bottom - top < .25 * content_height:
            continue
        in_zone = [l for l in lines if top <= l.yc <= bottom]
        crossing = [l for l in in_zone if l.x0 < g < l.x1]
        if len(crossing) > .15 * max(1, len(in_zone)):
            continue
        zone_left = [l.x1 for l in left if top <= l.yc <= bottom]
        zone_right = [l.x0 for l in right if top <= l.yc <= bottom]
        if not zone_left or not zone_right:
            continue
        left_edge, right_edge = max(zone_left), min(zone_right)
        if right_edge - left_edge < 8:
            continue
        # Right-aligned dates/locations are not a column: nearly every fragment on
        # one side is short and shares a baseline with a line on the other side.
        if _aligned_annotations(right, left) or _aligned_annotations(left, right):
            continue
        score = min(left_chars, right_chars) / total_chars - len(crossing) / max(1, len(in_zone)) + min(right_edge - left_edge, 60) / 400
        if best is None or score > best[0] + 1e-9:
            best = (score, left_edge, right_edge)
    return (best[1], best[2]) if best else None


def _aligned_annotations(side, other):
    """True when ``side`` is a strip of per-entry annotations (dates, locations).

    Such fragments are short, hug one shared edge (right-aligned dates end at the
    margin), each sits on the same baseline as an entry title on the other side,
    and the strip has no vertical run of its own: an annotation never has another
    annotation directly below it without a paired line in between.
    """
    if len(side) < 3:
        return False
    if any(len(line.text) > 40 for line in side):
        return False
    def paired(line):
        return any(min(line.y1, o.y1) - max(line.y0, o.y0) >= .6 * min(line.height, o.height) for o in other)
    if sum(paired(line) for line in side) < .85 * len(side):
        return False
    right_spread = max(l.x1 for l in side) - min(l.x1 for l in side)
    left_spread = max(l.x0 for l in side) - min(l.x0 for l in side)
    if min(right_spread, left_spread) > 6:
        return False
    ordered = sorted(side, key=lambda line: line.y0)
    stacked = sum(1 for a, b in zip(ordered, ordered[1:]) if b.y0 - a.y1 <= .6 * a.height)
    return stacked <= .15 * len(side)


def _classify(lines, gutter):
    left_edge, right_edge = gutter
    for line in lines:
        if line.x1 <= right_edge - .5:
            line.column = 'left'
        elif line.x0 >= left_edge + .5:
            line.column = 'right'
        else:
            line.column = 'full'


def _order_band(band, median_height):
    if not band:
        return []
    band = sorted(band, key=lambda line: line.y0)
    # A short header row block (name left, contact right) separated by clear
    # whitespace from the column body is read before that body begins.
    threshold = max(2.0 * median_height, 18.0)
    groups, current, reach = [], [band[0]], band[0].y1
    for line in band[1:]:
        if line.y0 - reach >= threshold and max(sum(l.column == 'left' for l in current), sum(l.column == 'right' for l in current)) <= 8:
            groups.append(current)
            current = []
        current.append(line)
        reach = max(reach, line.y1)
    groups.append(current)
    ordered = []
    for group in groups:
        for column in ('left', 'right', 'full'):
            ordered.extend(reading_sort([l for l in group if l.column == column]))
    return ordered


def _label_rail(lines, width, is_heading):
    """Detect a narrow rail of section labels beside one content stream.

    Returns (labels, content) or None. Labels are merged when a heading wraps
    (PROFESSIONAL / SUMMARY). Each label must look like a heading.
    """
    content_x = Counter(round(line.x0) for line in lines if line.x0 > width * .2)
    if not content_x:
        return None
    edge = min(x for x, count in content_x.items() if count >= 2) if any(count >= 2 for count in content_x.values()) else None
    if edge is None:
        return None
    rail = sorted((line for line in lines if line.x1 < edge - 4), key=lambda line: line.y0)
    content = [line for line in lines if line.x0 >= edge - 12]
    if len(rail) < 3 or len(rail) + len(content) != len(lines):
        return None
    labels = []
    for line in rail:
        last = labels[-1] if labels else None
        if last and line.y0 - last.y1 <= .9 * line.size and abs(line.size - last.size) <= .6 and not is_heading(last.text):
            labels[-1] = Line(last.x0, last.y0, max(last.x1, line.x1), line.y1, last.text + ' ' + line.text, last.html + ' ' + line.html, last.size, last.page, False, 'full')
        else:
            labels.append(Line(line.x0, line.y0, line.x1, line.y1, line.text, line.html, line.size, line.page, False, 'full'))
    headed = sum(1 for label in labels if is_heading(label.text) or generic_heading(label.text))
    if headed < max(3, .6 * len(labels)) or any(len(label.text.split()) > 5 for label in labels):
        return None
    if sum(len(line.text) for line in content) < 4 * sum(len(label.text) for label in labels):
        return None
    return labels, content


def _insert_labels(labels, content):
    """Place each label before the content line that starts its section.

    The section starts after the largest vertical gap in the content close to the
    label (section spacing exceeds line spacing), or at the first line after it.
    """
    content = reading_sort(content)
    positions = []
    for label in labels:
        window = max(3 * label.height, 30.0)
        candidates = [index for index, line in enumerate(content) if label.y0 - window <= line.y0 <= label.y1 + 2]
        start = next((index for index, line in enumerate(content) if line.y1 > label.y0), len(content))
        if candidates:
            best, best_gap = None, -1.0
            for index in candidates:
                gap = content[index].y0 - content[index - 1].y1 if index > 0 else window
                if gap > best_gap + .5:
                    best, best_gap = index, gap
            start = best
        positions.append(start)
    # Labels never move content out of order; keep insertion points monotonic.
    for i in range(1, len(positions)):
        positions[i] = max(positions[i], positions[i - 1])
    ordered, cursor = [], 0
    for label, position in zip(labels, positions):
        ordered.extend(content[cursor:position])
        ordered.append(label)
        cursor = position
    return ordered + content[cursor:]


def order_lines(lines, width, header_bottom=None, is_heading=lambda text: False):
    """Return lines in reading order and the detected gutter (or None).

    ``header_bottom`` marks the top of the first section heading on page one. A
    compact identity header above it is read row by row before any columns.
    """
    header = []
    if header_bottom is not None:
        header = [line for line in lines if line.y1 <= header_bottom + 1]
        lines = [line for line in lines if line.y1 > header_bottom + 1]
    for line in header:
        line.column = 'full'
    header = header_order(_merge_rows(header, is_heading), width)
    rail = _label_rail(lines, width, is_heading)
    if rail is not None:
        labels, content = rail
        for line in content:
            line.column = 'full'
        return header + _insert_labels(labels, _merge_rows(content, is_heading)), None
    gutter = find_gutter(lines, width)
    if gutter is None:
        for line in lines:
            line.column = 'full'
        return header + reading_sort(_merge_rows(lines, is_heading)), None
    _classify(lines, gutter)
    lines = _merge_rows(lines, is_heading)
    median_height = median(line.height for line in lines)
    ordered, band = list(header), []
    for line in sorted(lines, key=lambda line: (line.y0, line.x0)):
        if line.column == 'full':
            ordered.extend(_order_band(band, median_height))
            band = []
            ordered.append(line)
        else:
            band.append(line)
    ordered.extend(_order_band(band, median_height))
    return ordered, gutter


def generic_heading(text):
    """All-caps short line such as AWARDS or VOLUNTEERING (no digits, contact data or sentences)."""
    value = text.strip().rstrip(':')
    return bool(CAPS_HEADING.fullmatch(value)) and len(value.split()) <= 4 and not re.search(r'[@\d|]', value)


def paragraphs(ordered, is_heading: Callable[[str], bool]):
    """Rejoin wrapped lines into paragraphs and list items without dropping text."""
    right_edge = {}
    for line in ordered:
        right_edge[line.column] = max(right_edge.get(line.column, 0), line.x1)
    left_edge = {}
    for line in ordered:
        left_edge[line.column] = min(left_edge.get(line.column, line.x0), line.x0)
    result, current, start_x, seen_heading = [], None, 0.0, False
    for line in ordered:
        heading = is_heading(line.text) or (seen_heading and generic_heading(line.text))
        soft = bool(SOFT_BULLET.match(line.text)) and not line.bullet
        if soft:
            previous = current['last'] if current is not None else None
            continuation = previous is not None and not current['heading'] and previous.column == line.column and abs(line.x0 - start_x) <= 4 and 0 <= line.y0 - previous.y1 <= .75 * previous.size and not re.search(r'[.!?:]$', previous.text)
            if not continuation:
                stripped = SOFT_BULLET.sub('', line.text)
                html = re.sub(r'^((?:<[^>]+>)*)\s*[\u00b7\u2024]\s+', r'\1', line.html)
                line = Line(line.x0, line.y0, line.x1, line.y1, stripped, html, line.size, line.page, True, line.column, True)
        if current is not None:
            previous = current['last']
            column_width = max(40.0, right_edge[previous.column] - left_edge[previous.column])
            near_edge = previous.x1 >= right_edge[previous.column] - max(.25 * column_width, 3 * previous.size)
            gap = line.y0 - previous.y1
            if current['glyph']:
                # The line box starts at the bullet glyph; wrapped text is indented past it.
                aligned = start_x + 2 < line.x0 <= start_x + 24
            else:
                aligned = abs(line.x0 - start_x) <= 4 or (current['bullet'] and line.x0 >= start_x - 4 and line.x0 - start_x <= 18)
            if re.search(r'[.!?]$', previous.text) and line.text[:1].isupper():
                # A finished sentence continues only when the line was visibly full.
                near_edge = previous.x1 >= right_edge[previous.column] - 4 * previous.size
            # Comma-continued lists (skills laid out as tags) may use wider row gaps.
            gap_limit = 1.6 * previous.size if previous.text.endswith(',') else .75 * previous.size
            joins = (
                not heading and not current['heading'] and not line.bullet
                and line.column == previous.column and line.page == previous.page
                and abs(line.size - previous.size) <= .6 and -2 <= gap <= gap_limit and aligned
                and (near_edge or bool(CONTINUES.search(previous.text)))
            )
            if joins:
                separator = '' if previous.text.endswith('-') and line.text[:1].islower() else ' '
                current['text'] += separator + line.text
                current['html'] += separator + line.html
                current['last'] = line
                continue
            result.append(current)
        current = {'text': line.text, 'html': line.html, 'size': line.size, 'page': line.page, 'column': line.column, 'bullet': line.bullet, 'glyph': line.glyph, 'x0': line.x0, 'y0': line.y0, 'last': line, 'heading': heading}
        start_x = line.x0
        seen_heading = seen_heading or heading
    if current is not None:
        result.append(current)
    return [Paragraph(item['text'], item['html'], item['size'], item['page'], item['column'], item['bullet'], item['x0'], item['y0']) for item in result]


def masthead_bottom(lines, first_heading_top):
    """Boundary between the identity header and the body.

    The header ends at the last clear whitespace gap above the first section
    heading, so a wrapped label (PROFESSIONAL / SUMMARY) is not cut in half.
    """
    above = sorted((line for line in lines if line.y0 < first_heading_top - .5), key=lambda line: line.y0)
    if not above:
        return first_heading_top
    threshold = max(12.0, 1.2 * median(line.height for line in above))
    boundary, reach = first_heading_top, above[0].y1
    for line in above[1:]:
        if line.y0 - reach >= threshold:
            boundary = line.y0
        reach = max(reach, line.y1)
    if first_heading_top - reach >= threshold:
        boundary = first_heading_top
    return boundary - 1.5


def analyze_document(pdf, is_heading: Callable[[str], bool], page_limit: int | None = None):
    """Analyze a PyMuPDF document. Returns one PageLayout per page."""
    raw_pages = []
    for index, page in enumerate(pdf):
        if page_limit is not None and index >= page_limit:
            break
        lines, removed, sidebar = page_lines(page, index + 1)
        raw_pages.append((page, lines, removed, sidebar))
    # Running headers/footers: short edge lines on later pages that repeat text from
    # another page (for example the candidate name printed at the top of page 2).
    seen = {}
    for page, lines, _, _ in raw_pages:
        for line in lines:
            seen.setdefault(line.text.strip().lower(), set()).add(line.page)
    layouts = []
    for page, lines, removed, sidebar in raw_pages:
        height = page.rect.height
        kept = []
        for line in lines:
            edge = line.y1 < height * .09 or line.y0 > height * .91
            if edge and line.page > 1 and not line.bullet and len(line.text) <= 80 and len(seen[line.text.strip().lower()]) > 1:
                removed.append(line.text)
                continue
            kept.append(line)
        header_bottom = None
        if kept and kept[0].page == 1:
            tops = [line.y0 for line in kept if is_heading(line.text)]
            # Only a compact masthead; a page without early headings keeps column order.
            if tops and min(tops) <= .35 * height:
                header_bottom = masthead_bottom(kept, min(tops))
        ordered, gutter = order_lines(kept, page.rect.width, header_bottom, is_heading)
        layout = PageLayout(index_of(page, raw_pages), page.rect.width, height, paragraphs(ordered, is_heading), removed=removed)
        if gutter:
            layout.columns, layout.gutter = 2, (gutter[0] + gutter[1]) / 2
            left = [l for l in kept if l.column == 'left']
            right = [l for l in kept if l.column == 'right']
            left_width = max(l.x1 for l in left) - min(l.x0 for l in left)
            right_width = max(l.x1 for l in right) - min(l.x0 for l in right)
            layout.left_share = round(left_width / max(1.0, left_width + right_width), 3)
        if sidebar:
            layout.sidebar_fill, layout.sidebar_side = sidebar[0], sidebar[1]
        layouts.append(layout)
    return layouts


def index_of(page, raw_pages):
    return next(position for position, item in enumerate(raw_pages, start=1) if item[0] is page)
