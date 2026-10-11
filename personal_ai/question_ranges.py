"""Explicit reading-group anchors, retaining original source offsets and wording."""
import re

# Unicode decimal digits and common typography/OCR range separators.
RANGE = r'(\d{1,4})\s*(?:[-‐‑‒–—−~～〜﹏至到]|\bto\b|\bthrough\b)\s*(\d{1,4})'
READING_RANGE = re.compile(
    r'(?:請\s*)?(?:閱讀|讀)[^：:]{0,100}?(?:回答|作答)\s*(?:第\s*)?'
    + RANGE + r'\s*題'
    + r'|(?:read|refer\s+to)[^:]{0,140}?(?:answer\s+)?(?:the\s+)?questions?\s*' + RANGE
    + r'|(?:以下|下列|下方)[^\n：:]{0,40}?(?:材料|文章|短文|詩文|對話|圖表)[^\n：:]{0,30}?'
    + r'(?:適用|供|回答|作答)\s*(?:第\s*)?' + RANGE + r'\s*題', re.I)


def reading_ranges(text):
    """Only explicit material/question instructions, not section or numeric ranges."""
    anchors = []
    for match in READING_RANGE.finditer(text):
        values = [value for value in match.groups() if value is not None]
        lower, upper = map(int, values)
        if 0 < lower <= upper:
            anchors.append(dict(start=match.start(), end=match.end(),
                                question_from=lower, question_to=upper,
                                instruction=match.group()))
    return anchors


def preceding_range(anchors, position):
    return next((anchor for anchor in reversed(anchors) if anchor['start'] <= position), None)
