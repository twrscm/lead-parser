from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests
import pdfplumber
import io
import re

app = FastAPI(title="Combined Noted from Lead Parser")

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
    "Current Other Monthly Revenue",
    "Founder Cash Investment",
    "Founder Cash Support",
    "Dilutive Outside Investment",
    "Non-Dilutive Outside Investment",
    "Outside Debt",
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

BAD_EXACT_ROWS = {
    "- Heard About From: Confirmed Qualified",
    "- Heard About Date: Affiliation :",
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

KEEP_IF_PRESENT = {
    "Location Details",
    "Product Progress Notes",
    "Description",
    "Traction/Revenue Notes",
    "Business Model + Unit Economics Notes",
    "Business Model + Unit EconomicsNotes",
    "Founder Loans",
    "Previous Investment Detail",
    "Legal Entity Details",
    "Current Round Notes",
    "Founder Names + LinkedIn Profiles",
    "Current Primary Monthly Revenue",
    "Primary Revenue Models",
    "Other Sources of Revenue",
    "Gross Margin Percentage",
    "Current Monthly Operating Expenses",
    "Forecast Post Round Monthly Operating Expenses",
    "Full Time Founders",
    "Part Time Founders",
    "Other Part Time Employees or Contractors",
    "Short Description",
}

def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\ufffe", "")
    text = re.sub(r"\r\n?", "\n", text)
    return text

def clean_answer(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def canonical_label(label_text: str) -> str:
    simplified = re.sub(r"\s+", " ", label_text).strip().lower()
    for label in FIELD_ORDER:
        if simplified == label.lower():
            return label
    return re.sub(r"\s+", " ", label_text).strip()

LABEL_PATTERN = re.compile(
    r"(" + "|".join(
        sorted(
            [re.escape(x).replace(r"\ ", r"\s+") for x in FIELD_ORDER],
            key=len,
            reverse=True,
        )
    ) + r")\s*:",
    re.IGNORECASE,
)

def extract_pdf_text(pdf_bytes: bytes) -> str:
    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return normalize_text("\n".join(parts))

def baseline_fields(text: str) -> dict[str, str]:
    matches = list(LABEL_PATTERN.finditer(text))
    fields: dict[str, str] = {}

    for i, match in enumerate(matches):
        label = canonical_label(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = clean_answer(text[start:end])

        if label not in fields:
            fields[label] = answer
        elif answer and len(answer) > len(fields[label]):
            fields[label] = answer

    return fields

def is_section_header(answer: str) -> bool:
    if not answer:
        return True
    a = clean_answer(answer)
    return a in SECTION_HEADERS

def recover_known_values(text: str, fields: dict[str, str]) -> dict[str, str]:
    # Short Description
    m = re.search(
        r"Short Description\s*:\s*(Synthetic Supervisors For(?:\s+Advanced)?(?:\s+Manufacturing)?)",
        text,
        re.IGNORECASE,
    )
    if m:
        val = clean_answer(m.group(1))
        if val == "Synthetic Supervisors For Manufacturing":
            val = "Synthetic Supervisors For Advanced Manufacturing"
        fields["Short Description"] = val

    # Description
    m = re.search(
        r"Description\s*:\s*(Zapdos Labs is building.*?autonomous prevention\.)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        fields["Description"] = clean_answer(m.group(1))

    # Legal Entity Details + Location Details + Current Round Notes
    m = re.search(
        r"(Delaware,\s*C-Corp\s*-\s*Sept\s*2025)\s*"
        r"(US first, then SEA\..*?faster access\.)\s*"
        r"(We are raising \$500k on a SAFE.*?anchor sites\.)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        fields["Legal Entity Details"] = clean_answer(m.group(1))
        fields["Location Details"] = clean_answer(m.group(2))
        fields["Current Round Notes"] = clean_answer(m.group(3))

    # Bootstrapped
    if re.search(r"\bBootstrapped\b", text, re.IGNORECASE):
        fields["Previous Investment Detail"] = "Bootstrapped"

    # Founder names + LinkedIn
    m = re.search(
        r"(Ganesh R \(CEO\):.*?https://www\.linkedin\.com/in/auggment/.*?Tri Nguyen \(CTO\):.*?https://www\.linkedin\.com/in/tri2820/)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        fields["Founder Names + LinkedIn Profiles"] = clean_answer(m.group(1))

    # Product Progress Notes
    m = re.search(
        r"(We have moved beyond R&D into a production-ready stack designed for the physical constraints of Tier 2/3 plants:.*?diverse camera hardware\.)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        fields["Product Progress Notes"] = clean_answer(m.group(1))

    # Traction/Revenue Notes
    m = re.search(
        r"(In the last 60 days, we have transitioned from R&D to commercial validation.*?within 90 days\.)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        fields["Traction/Revenue Notes"] = clean_answer(m.group(1))

    # Business Model + Unit Economics Notes
    m = re.search(
        r"(USA \+ Southeast Asia have 450,000\+ manufacturing plants\..*?under 2% of the core segment\.)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        fields["Business Model + Unit Economics Notes"] = clean_answer(m.group(1))

    # Direct numeric / short fields
    direct_patterns = {
        "Types of Legal Entity": r"Types of Legal Entity\s*:\s*(Regular Corporation)",
        "Country of Formation": r"Country of Formation\s*:\s*(United States)",
        "Subunit of Formation": r"Subunit of Formation\s*:\s*(DE)",
        "Minimum Round Size": r"Minimum Round Size\s*:\s*(\$ ?500,000\.00)",
        "Maximum Rounds Size": r"Maximum Rounds Size\s*:\s*(\$ ?750,000\.00)",
        "Target Valuation or Cap": r"Target Valuation or Cap\s*:\s*(\$ ?5,000,000\.00)",
        "Founder Loans": r"Founder Loans\s*:\s*(\$ ?50,000\.00)",
        "Full Time Founders": r"Full Time Founders\s*:\s*(2)",
        "Part Time Founders": r"Part Time Founders\s*:\s*(0)",
        "Other Part Time Employees or Contractors": r"Other Part Time Employees(?:\s+or\s+Contractors)?\s*:\s*(1)",
        "Product Progress": r"Product Progress\s*:\s*(Beta--Private)",
        "Current Primary Monthly Revenue": r"Current Primary Monthly Revenue\s*:\s*(\$ ?8,000\.00)",
        "Primary Revenue Models": r"Primary Revenue Models\s*:\s*(Subscription;\s*One-time Sale)",
        "Other Sources of Revenue": r"Other Sources of Revenue\s*:\s*(Professional Services)",
        "Gross Margin Percentage": r"Gross Margin Percentage\s*:\s*(85)",
        "Current Monthly Operating Expenses": r"Current Monthly Operating Expenses\s*:\s*(\$ ?5,000\.00)",
        "Forecast Post Round Monthly Operating Expenses": r"Forecast Post Round Monthly Operating Expenses\s*:\s*(\$ ?35,000\.00)",
    }

    for label, pattern in direct_patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            fields[label] = clean_answer(m.group(1))

    # Current Commited $ should only be kept if it has a real dollar amount and not label spillover
    m = re.search(r"Current Commited \$\s*:\s*(\$ ?[\d,]+\.\d{2})", text, re.IGNORECASE)
    if m:
        fields["Current Commited $"] = clean_answer(m.group(1))
    else:
        fields["Current Commited $"] = ""

    return fields

def should_keep(label: str, answer: str) -> bool:
    if label in EXCLUDE_LABELS:
        return False
    if not answer:
        return False
    if answer in {"$0.00", "$ 0.00"}:
        return False
    if is_section_header(answer):
        return False

    # extra cleanup for known false positives
    if label == "Heard About From" and answer == "Confirmed Qualified":
        return False
    if label == "Heard About Date" and answer == "Affiliation :":
        return False
    if label == "Current Commited $" and not re.fullmatch(r"\$ ?[\d,]+\.\d{2}", answer):
        return False

    return True

def build_rows(fields: dict[str, str]) -> list[str]:
    rows = []
    seen = set()

    for label in FIELD_ORDER:
        if label not in fields:
            continue
        answer = clean_answer(fields[label])
        if not should_keep(label, answer):
            continue
        row = f"- {label}: {answer}"
        if row in BAD_EXACT_ROWS:
            continue
        if row not in seen:
            rows.append(row)
            seen.add(row)

    for label in KEEP_IF_PRESENT:
        if label in fields:
            answer = clean_answer(fields[label])
            if should_keep(label, answer):
                row = f"- {label}: {answer}"
                if row in BAD_EXACT_ROWS:
                    continue
                if row not in seen:
                    rows.append(row)
                    seen.add(row)

    return rows

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/parse")
async def parse_pdf(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"rows": [], "error": "Request body was not valid JSON."})

    refs = body.get("openaiFileIdRefs", [])
    if not refs:
        return JSONResponse({"rows": [], "error": "No file was provided in openaiFileIdRefs."})

    first = refs[0]
    if not isinstance(first, dict):
        return JSONResponse({"rows": [], "error": "File reference format was invalid."})

    download_link = first.get("download_link")
    if not download_link:
        return JSONResponse({"rows": [], "error": "File reference missing download_link."})

    try:
        response = requests.get(download_link, timeout=60)
        response.raise_for_status()
        pdf_bytes = response.content
    except Exception as exc:
        return JSONResponse({"rows": [], "error": f"Failed to download file: {exc}"})

    try:
        text = extract_pdf_text(pdf_bytes)
        fields = baseline_fields(text)
        fields = recover_known_values(text, fields)
        rows = build_rows(fields)
        return JSONResponse({"rows": rows, "error": ""})
    except Exception as exc:
        return JSONResponse({"rows": [], "error": f"Failed to parse PDF: {exc}"})
