"""Personal details (formId 17) parser (moved from app.app; re-exported from app.app)."""

import re


# ── Personal details (formId 17) ───────────────────────────────
def parse_personal_details(html):
    """Extract key-value pairs from the personal details page (formId 17).
    The portal renders label/value table rows inside #divMainDetails."""
    out = {}
    for m in re.finditer(
            r'<td[^>]*>\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*(.*?)\s*</td>', html, re.S):
        key = re.sub(r'<[^>]+>', '', m.group(1)).strip().rstrip(':').strip()
        val = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if key and val and key.lower() not in ('', 's.no', 's. no'):
            out[key] = val
    return out
