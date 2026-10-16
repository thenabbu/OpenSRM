"""Internal marks parser (moved from app.app; re-exported from app.app)."""

import re

# audit: portal dates ('12/09/2026', '12-Sep-2026') also match the score
# pattern \d+/\d+ — parsers must recognize date cells before scanning scores
_DATE_CELL_RE = re.compile(r"\d{1,2}[/ -](?:\w{3,9}|\d{1,2})[/ -]\d{2,4}")

# -- Internal marks (formId 13) --
def parse_marks(html):
    """Parse internal marks from studentInternalMarkDetails.jsp.
    Returns (marks_list, subject_map) where subject_map maps code -> {id, status}."""
    out = []
    if not html:
        return out, {}   # audit: ALWAYS a 2-tuple — callers unpack (out, subject_map)
    if re.search(r"no\s+record\s+found", html, re.I):
        return out, {}
    # Extract subjectId + status from onclick="funViewComponentWiseMarks(id, code, desc, status)"
    subject_map = {}
    for fm in re.finditer(r"funViewComponentWiseMarks\('(\d+)',\s*'([^']+)',\s*'([^']+)',\s*(\d+)\)", html):
        sid, scode, _sdesc, sstatus = fm.group(1), fm.group(2), fm.group(3), int(fm.group(4))
        subject_map[scode] = {"id": int(sid), "status": sstatus}
    table_m = re.search(r"<table[^>]*>.*?<tr[^>]*>(.*?)</tr>(.*?)</table>", html, re.S)
    if not table_m:
        return out, {}   # audit: 2-tuple (bare list crashed the unpack, was swallowed -> silent empty marks)
    headers = [re.sub(r"<[^>]+>", "", h).strip().lower()
               for h in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", table_m.group(1), re.S)]
    if not headers or not any("code" in h for h in headers):
        return out, {}   # audit: 2-tuple (see above)
    code_i = next((i for i, h in enumerate(headers) if "code" in h), 0)
    desc_i = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ("desc", "course", "subject"))), 1)
    test_i = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ("test", "exam", "assess", "component"))), None)
    by_code = {}
    order = []
    pair_re = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_m.group(2), re.S):
        cells = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 3:
            continue
        code = cells[code_i] if code_i < len(cells) else ""
        if not code or re.match(r"total|s\.?\s*no", code, re.I):
            continue
        scored = maximum = 0.0
        for cell in cells:
            if _DATE_CELL_RE.search(cell):
                continue  # audit: '12/09/2026' would match pair_re as 12/9
            m = pair_re.search(cell)
            if m:
                scored, maximum = float(m.group(1)), float(m.group(2))
                break
        if maximum <= 0:
            continue
        desc = cells[desc_i] if desc_i < len(cells) and desc_i != code_i else ""
        test_name = ""
        if test_i is not None and test_i < len(cells):
            val = cells[test_i].strip()
            if val and val.lower() not in ("view details", "nil", "-", ""):
                test_name = val
        if not test_name:
            if maximum <= 5:
                n = sum(1 for v in by_code.get(code, {}).get("components", [])
                        if v.get("max", 0) <= 5) + 1
                test_name = f"FT{n}"
            else:
                n = sum(1 for v in by_code.get(code, {}).get("components", [])
                        if v.get("max", 0) > 5) + 1
                test_name = f"CT {n}"
        if code not in by_code:
            by_code[code] = {"code": code, "title": desc, "components": [],
                             "scored_total": 0.0, "max_total": 0.0}
            order.append(code)
        elif not by_code[code]["title"] and desc:
            by_code[code]["title"] = desc
        by_code[code]["components"].append(
            {"name": test_name, "scored": scored, "max": maximum})
        by_code[code]["scored_total"] = round(by_code[code]["scored_total"] + scored, 2)
        by_code[code]["max_total"] = round(by_code[code]["max_total"] + maximum, 2)
    return [by_code[c] for c in order], subject_map

def _parse_component_inner(html):
    """Parse inner JSP response for component-wise marks breakdown."""
    comps = []
    if not html:
        return comps
    if re.search(r"no\s+record\s+found", html, re.I):
        return comps
    pair_re = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")
    date_re = _DATE_CELL_RE  # shared: broadened to numeric months too
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 2:
            continue
        scored = maximum = 0.0
        for cell in cells:
            if _DATE_CELL_RE.search(cell):
                continue  # audit: '12/09/2026' would match pair_re as 12/9
            m = pair_re.search(cell)
            if m:
                scored, maximum = float(m.group(1)), float(m.group(2))
                break
        if maximum <= 0:
            continue
        name, entered = "", ""
        # component JSP rows: [entered_on, component_name, score/max]
        if len(cells) >= 3 and date_re.search(cells[0]):
            entered = cells[0]
            if not pair_re.search(cells[1]):
                name = cells[1]
        if not name:
            for cell in cells:
                t = cell.strip()
                if t and not pair_re.search(t) and t.lower() not in ("", "-", "nil", "total"):
                    name = t
                    break
        if not name:
            name = f"Assessment {len(comps)+1}"
        comps.append({"name": name, "entered": entered, "scored": scored, "max": maximum})
    return comps
