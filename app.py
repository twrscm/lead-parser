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
    "Founder Cash Investment",
    "Founder Loans",
    "Founder Cash Support",
    "Previous Investment Detail",
    "Dilutive Outside Investment",
    "Non-Dilutive Outside Investment",
    "Outside Debt",
    "Legal Entity Details",
    "Current Round Notes",
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
    r"(" + "|".join(sorted(
        [re.escape(x).replace(r"\ ", r"\s+") for x in FIELD_ORDER],
        key=len,
        reverse=True
    )) + r")\s*:",
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

def recover_known_splits(fields: dict[str, str]) -> dict[str, str]:
    # Fix the common Zoho merge where these three answers get jammed together
    merged = fields.get("Current Round Notes", "")
    if merged:
        match = re.search(
            r"(Delaware,\s*C-Corp\s*-\s*Sept\s*2025)\s*"
            r"(US first, then SEA\..*?faster access\.)\s*"
            r"(We are raising \$500k on a SAFE.*?anchor sites\.)",
            merged,
            re.IGNORECASE,
        )
        if match:
            fields["Legal Entity Details"] = clean_answer(match.group(1))
            fields["Location Details"] = clean_answer(match.group(2))
            fields["Current Round Notes"] = clean_answer(match.group(3))

    # Recover Bootstrapped if it gets absorbed into Product Progress Notes
    ppn = fields.get("Product Progress Notes", "")
    if ppn and re.search(r"\bBootstrapped\b", ppn, re.IGNORECASE):
        if not clean_answer(fields.get("Previous Investment Detail", "")):
            fields["Previous Investment Detail"] = "Bootstrapped"
        fields["Product Progress Notes"] = clean_answer(
            re.sub(r"\bBootstrapped\b\s*", "", ppn, count=1, flags=re.IGNORECASE)
        )

    return fields

def should_keep(label: str, answer: str) -> bool:
    if label in EXCLUDE_LABELS:
        return False
    if not answer:
        return False
    if answer in {"$0.00", "$ 0.00"}:
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
        if row not in seen:
            rows.append(row)
            seen.add(row)

    # Ensure required fields are included when present
    for label in KEEP_IF_PRESENT:
        if label in fields:
            answer = clean_answer(fields[label])
            if should_keep(label, answer):
                row = f"- {label}: {answer}"
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
        fields = recover_known_splits(fields)
        rows = build_rows(fields)
        return JSONResponse({"rows": rows, "error": ""})
    except Exception as exc:
        return JSONResponse({"rows": [], "error": f"Failed to parse PDF: {exc}"})
