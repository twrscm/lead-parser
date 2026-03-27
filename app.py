from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests
import pdfplumber
import io
import re

app = FastAPI(title="Combined Noted from Lead Parser")
APP_VERSION = "generic-template-v1"

EXCLUDE_LABELS = {
    "Review Decision Date",
    "Lead Status",
    "Lead Grade",
    "Created By",
    "Modified By",
    "Generated Email",
    "Company",
    "Lead Name",
    "Lead Source",
    "Lead Owner",
    "Spoke/Emailed With",
    "Email",
    "Mobile",
    "Website",
}

SECTION_HEADERS = {
    "Lead Information",
    "New Lead Information",
    "Startup Overview",
    "New Startup Overview",
    "Old Startup Overview",
    "Extended Description and Notes",
    "Old Location",
    "New Location",
    "New Potential Deal Overview",
    "Old Potential Deal Overview",
    "Potential Deal Details",
    "New Previous Investment",
    "New Founders and Employees",
    "Old Founders and Employee",
    "Founder Detail",
    "Progress Overview",
    "New Financials Overview",
    "Old Financials Overview",
    "Progress and Financial Detail",
    "Next Round",
    "Evaluation Workflow",
    "Combined Noted from Lead",
    "Address",
    "Visit Summary",
    "Notes",
    "Cadences",
    "Attachments",
    "Products",
    "Open Activities",
    "Closed Activities",
    "Invited Meetings",
    "Emails",
    "Zoho Survey",
    "Zoho Desk",
    "No records found",
}

FIELD_ORDER = [
    "Company",
    "Co. Previously/Also Known As",
    "Lead Name",
    "Lead Source",
    "Referrer Name",
    "Lead Owner",
    "Spoke/Emailed With",
    "Email",
    "Mobile",
    "Tag",
    "Referrer Affiliation",
    "Heard About From",
    "Heard About Date",
    "Confirmed Qualified Source",
    "Confirmed Qualified Affiliation",
    "Confirmed Qualified Date",
    "Short Description",
    "Website",
    "CrunchBase Link",
    "Old Web Site",
    "Description",
    "Primary City",
    "Primary US State or Country",
    "Types of Legal Entity",
    "Legal Entity Details",
    "Location Details",
    "Country of Formation",
    "Subunit of Formation",
    "Region",
    "Minimum Round Size",
    "Maximum Rounds Size",
    "Target Valuation or Cap",
    "Terms Already Set By Investor",
    "Total Current Commitments",
    "Old Desired Round Size",
    "Desired Valuation/Cap",
    "Current Commited $",
    "Current Sources (multi-select)",
    "Previous Investment",
    "Previous Investment Sources (multi-select)",
    "Current Round Notes",
    "Founder Cash Investment",
    "Founder Loans",
    "Founder Cash Support",
    "Previous Investment Detail",
    "Dilutive Outside Investment",
    "Non-Dilutive Outside Investment",
    "Outside Debt",
    "Full Time Founders",
    "Part Time Founders",
    "Other Full Time Employees",
    "Other Part Time Employees or Contractors",
    "Founder Names + LinkedIn Profiles",
    "Product Progress",
    "Product Progress Notes",
    "Currently Generating Revenue",
    "Signed Contracts",
    "Current Primary Monthly Revenue",
    "Primary Revenue Models",
    "Current Other Monthly Revenue",
    "Other Sources of Revenue",
    "Gross Margin Percentage",
    "Current Monthly Operating Expenses",
    "Forecast Post Round Monthly Operating Expenses",
    "Most Recent Month's Revenues",
    "Most Recent Month's Gross Expenses",
    "Forecast Post-Round Gross Expenses",
    "Monthly Revenue Primary Product or Service",
    "Revenue Models for Primary Product or Service",
    "Traction/Revenue Notes",
    "Business Model + Unit Economics Notes",
    "Business Model + Unit EconomicsNotes",
    "Milestone and Timing of Next Round",
    "Initial Contact Date",
    "Review Decision Date",
    "Required Clarification",
    "Lead Status",
    "Lead Grade",
    "Lead Processing Notes",
    "Assigned To",
    "Created By",
    "Modified By",
    "Combined Noted from Lead",
    "Generated Email",
    "Street",
    "Street 2",
    "City",
    "State",
    "Country",
    "Most Recent Visit",
    "Average Time Spent (Minutes)",
    "Referrer",
    "First Visit",
    "First Page Visited",
    "Number Of Chats",
    "Visitor Score",
    "Days Visited",
]

LABEL_PATTERN = re.compile(
    r"(" + "|".join(sorted([re.escape(x).replace(r"\ ", r"\s+") for x in FIELD_ORDER], key=len, reverse=True)) + r")\s*:",
    re.IGNORECASE,
)

def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\ufffe", "")
    text = re.sub(r"\r\n?", "\n", text)
    return text

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()

def canonical_label(label_text: str) -> str:
    simplified = re.sub(r"\s+", " ", label_text).strip().lower()
    for label in FIELD_ORDER:
        if simplified == label.lower():
            return label
    return re.sub(r"\s+", " ", label_text).strip()

def extract_text(pdf_bytes: bytes) -> str:
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            out.append(p.extract_text() or "")
    return normalize_text("\n".join(out))

def is_blankish(answer: str) -> bool:
    a = clean(answer)
    return a == "" or a in {"$0.00", "$ 0.00"}

def is_section_header(answer: str) -> bool:
    return clean(answer) in SECTION_HEADERS

def is_bad_spillover(label: str, answer: str) -> bool:
    a = clean(answer)

    if label == "Heard About From" and a == "Confirmed Qualified":
        return True
    if label == "Heard About Date" and a == "Affiliation :":
        return True
    if label == "Region" and re.fullmatch(r"\d{4}", a):
        return True
    if label == "Signed Contracts" and (
        "Current Primary Monthly" in a
        or "Forecast Post Round" in a
        or "Monthly Operating Expenses" in a
        or "Revenue :" in a
        or "Expenses :" in a
    ):
        return True
    if label == "Current Commited $" and not re.fullmatch(r"\$ ?[\d,]+\.\d{2}", a):
        return True

    # generic section-header-like spillover
    if a in SECTION_HEADERS:
        return True

    return False

def baseline_fields(text: str) -> dict[str, str]:
    matches = list(LABEL_PATTERN.finditer(text))
    fields: dict[str, str] = {}

    for i, m in enumerate(matches):
        label = canonical_label(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = clean(text[start:end])

        if label not in fields:
            fields[label] = answer
        elif answer and len(answer) > len(fields[label]):
            fields[label] = answer

    return fields

def collect_nonlabel_lines(text: str) -> list[str]:
    lines = [clean(x) for x in text.split("\n")]
    out = []
    for line in lines:
        if not line:
            continue
        if line in SECTION_HEADERS:
            continue
        if LABEL_PATTERN.search(line):
            continue
        out.append(line)
    return out

def fill_simple_missing_fields(text: str, fields: dict[str, str]) -> dict[str, str]:
    # Short Description: capture same-line value, but if wrapped, combine nearest continuation
    if is_blankish(fields.get("Short Description", "")) or fields.get("Short Description") == "Synthetic Supervisors For":
        m = re.search(r"Short Description\s*:\s*(.+)", text, re.IGNORECASE)
        if m:
            first = clean(m.group(1))
            if first:
                if not re.search(r"(Manufacturing|SAAS|SaaS|Software|Platform|AI|Analytics|Automation)", first, re.IGNORECASE):
                    lines = text.split("\n")
                    for i, line in enumerate(lines):
                        if re.search(r"Short Description\s*:", line, re.IGNORECASE):
                            combined = clean(re.sub(r".*Short Description\s*:\s*", "", line, flags=re.IGNORECASE))
                            j = i + 1
                            while j < len(lines):
                                nxt = clean(lines[j])
                                if not nxt:
                                    j += 1
                                    continue
                                if LABEL_PATTERN.search(nxt) or nxt in SECTION_HEADERS:
                                    break
                                combined = clean(combined + " " + nxt)
                                j += 1
                                if len(combined.split()) >= 8:
                                    break
                            fields["Short Description"] = combined
                            break
                else:
                    fields["Short Description"] = first

    # Generic direct value recovery for simple money/number/text fields
    direct_patterns = {
        "Types of Legal Entity": r"Types of Legal Entity\s*:\s*([^\n]+)",
        "Country of Formation": r"Country of Formation\s*:\s*([^\n]+)",
        "Subunit of Formation": r"Subunit of Formation\s*:\s*([^\n]+)",
        "Minimum Round Size": r"Minimum Round Size\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Maximum Rounds Size": r"Maximum Rounds Size\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Target Valuation or Cap": r"Target Valuation or Cap\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Founder Cash Investment": r"Founder Cash Investment\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Founder Loans": r"Founder Loans\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Founder Cash Support": r"Founder Cash Support\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Dilutive Outside Investment": r"Dilutive Outside Investment\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Non-Dilutive Outside Investment": r"Non-Dilutive Outside Investment\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Outside Debt": r"Outside Debt\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Full Time Founders": r"Full Time Founders\s*:\s*(\d+)",
        "Part Time Founders": r"Part Time Founders\s*:\s*(\d+)",
        "Other Full Time Employees": r"Other Full Time Employees\s*:\s*(\d+)",
        "Other Part Time Employees or Contractors": r"Other Part Time Employees(?:\s+or\s+Contractors)?\s*:\s*(\d+)",
        "Product Progress": r"Product Progress\s*:\s*([^\n]+)",
        "Current Primary Monthly Revenue": r"Current Primary Monthly Revenue\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Primary Revenue Models": r"Primary Revenue Models\s*:\s*([^\n]+)",
        "Current Other Monthly Revenue": r"Current Other Monthly Revenue\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Other Sources of Revenue": r"Other Sources of Revenue\s*:\s*([^\n]+)",
        "Gross Margin Percentage": r"Gross Margin Percentage\s*:\s*(\d+)",
        "Current Monthly Operating Expenses": r"Current Monthly Operating Expenses\s*:\s*(\$ ?[\d,]+\.\d{2})",
        "Forecast Post Round Monthly Operating Expenses": r"Forecast Post Round Monthly Operating Expenses\s*:\s*(\$ ?[\d,]+\.\d{2})",
    }

    for label, pattern in direct_patterns.items():
        if is_blankish(fields.get(label, "")) or is_bad_spillover(label, fields.get(label, "")):
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                fields[label] = clean(m.group(1))

    return fields

def recover_grouped_sections(text: str, fields: dict[str, str]) -> dict[str, str]:
    lines = [clean(x) for x in text.split("\n")]

    # Legal Entity Details / Location Details / Current Round Notes
    if any(is_blankish(fields.get(k, "")) or is_bad_spillover(k, fields.get(k, "")) for k in ["Legal Entity Details", "Location Details", "Current Round Notes"]):
        for i, line in enumerate(lines):
            if re.search(r"Current Round Notes\s*:", line, re.IGNORECASE):
                collected = []
                j = i + 1
                while j < len(lines):
                    cur = lines[j]
                    if not cur:
                        j += 1
                        continue
                    if cur in SECTION_HEADERS:
                        j += 1
                        continue
                    if LABEL_PATTERN.search(cur):
                        break
                    collected.append(cur)
                    j += 1

                if collected:
                    # heuristic: first short line -> legal entity details
                    if len(collected) >= 1 and ("corp" in collected[0].lower() or "llc" in collected[0].lower() or "corporation" in collected[0].lower() or "s-corp" in collected[0].lower()):
                        if is_blankish(fields.get("Legal Entity Details", "")) or is_bad_spillover("Legal Entity Details", fields.get("Legal Entity Details", "")):
                            fields["Legal Entity Details"] = collected[0]

                    # next geographic lines until raising/funding sentence -> location details
                    loc_parts = []
                    round_parts = []
                    mode = "loc"
                    for part in collected[1:] if len(collected) > 1 else []:
                        if re.search(r"\b(raising|raise|funding|safe|post-money|valuation)\b", part, re.IGNORECASE):
                            mode = "round"
                        if mode == "loc":
                            loc_parts.append(part)
                        else:
                            round_parts.append(part)

                    if loc_parts and (is_blankish(fields.get("Location Details", "")) or is_bad_spillover("Location Details", fields.get("Location Details", ""))):
                        fields["Location Details"] = clean(" ".join(loc_parts))

                    if round_parts and (is_blankish(fields.get("Current Round Notes", "")) or is_bad_spillover("Current Round Notes", fields.get("Current Round Notes", ""))):
                        fields["Current Round Notes"] = clean(" ".join(round_parts))
                break

    # Founder names + profiles
    if is_blankish(fields.get("Founder Names + LinkedIn Profiles", "")):
        m = re.search(
            r"Founder Names \+ LinkedIn Profiles\s*:\s*(.*?)(?:Progress Overview|New Financials Overview)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean(m.group(1))
            if val and not is_section_header(val):
                fields["Founder Names + LinkedIn Profiles"] = val

    # Product Progress Notes
    if is_blankish(fields.get("Product Progress Notes", "")):
        m = re.search(
            r"Product Progress Notes\s*:\s*(.*?)(?:New Financials Overview|Old Financials Overview)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean(m.group(1))
            if val and not is_section_header(val):
                fields["Product Progress Notes"] = val

    # Traction/Revenue Notes
    if is_blankish(fields.get("Traction/Revenue Notes", "")):
        m = re.search(
            r"Traction/Revenue Notes\s*:\s*(.*?)(?:Business Model \+ Unit Economics Notes\s*:|Next Round|Evaluation Workflow)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean(m.group(1))
            if val and not is_section_header(val):
                fields["Traction/Revenue Notes"] = val

    # Business Model + Unit Economics Notes
    if is_blankish(fields.get("Business Model + Unit Economics Notes", "")) and is_blankish(fields.get("Business Model + Unit EconomicsNotes", "")):
        m = re.search(
            r"Business Model \+ Unit Economics ?Notes\s*:\s*(.*?)(?:Next Round|Evaluation Workflow)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean(m.group(1))
            if val and not is_section_header(val):
                fields["Business Model + Unit Economics Notes"] = val

    # Previous Investment Detail often contains Bootstrapped or similar short text
    if is_blankish(fields.get("Previous Investment Detail", "")):
        m = re.search(r"Previous Investment Detail\s*:\s*([^\n]+)", text, re.IGNORECASE)
        if m:
            fields["Previous Investment Detail"] = clean(m.group(1))

    return fields

def should_keep(label: str, answer: str) -> bool:
    a = clean(answer)
    if label in EXCLUDE_LABELS:
        return False
    if is_blankish(a):
        return False
    if is_section_header(a):
        return False
    if is_bad_spillover(label, a):
        return False
    return True

def build_rows(fields: dict[str, str]) -> list[str]:
    rows = []
    seen = set()

    for label in FIELD_ORDER:
        val = clean(fields.get(label, ""))
        if not should_keep(label, val):
            continue

        # normalize typo variant
        out_label = "Business Model + Unit Economics Notes" if label == "Business Model + Unit EconomicsNotes" else label

        row = f"- {out_label}: {val}"
        if row not in seen:
            rows.append(row)
            seen.add(row)

    return rows

@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION}

@app.post("/parse")
async def parse_pdf(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"rows": [], "error": "Request body was not valid JSON.", "version": APP_VERSION}

    refs = body.get("openaiFileIdRefs", [])
    if not refs:
        return {"rows": [], "error": "No file", "version": APP_VERSION}

    first = refs[0]
    if not isinstance(first, dict):
        return {"rows": [], "error": "Invalid file reference format", "version": APP_VERSION}

    link = first.get("download_link")
    if not link:
        return {"rows": [], "error": "No download link", "version": APP_VERSION}

    try:
        pdf_bytes = requests.get(link, timeout=60).content
    except Exception:
        return {"rows": [], "error": "Download failed", "version": APP_VERSION}

    try:
        text = extract_text(pdf_bytes)
        fields = baseline_fields(text)
        fields = fill_simple_missing_fields(text, fields)
        fields = recover_grouped_sections(text, fields)
        rows = build_rows(fields)
        return {"rows": rows, "version": APP_VERSION}
    except Exception as e:
        return {"rows": [], "error": f"Parse failed: {e}", "version": APP_VERSION}
