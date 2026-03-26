from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import pdfplumber
import io
import re

app = FastAPI(title="Combined Noted from Lead Parser", version="3.0.0")

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

def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\ufffe", "")
    text = re.sub(r"\r\n?", "\n", text)
    return text

LABEL_PATTERN = re.compile(
    r"(" + "|".join(sorted([re.escape(x).replace(r"\ ", r"\s+") for x in FIELD_ORDER], key=len, reverse=True)) + r")\s*:",
    re.IGNORECASE,
)

def extract_pdf_text(pdf_bytes: bytes) -> str:
    chunks = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            chunks.append(txt)
    return normalize_text("\n".join(chunks))

def clean_answer(s: str) -> str:
    s = normalize_text(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def canonical_label(label_text: str) -> str:
    simplified = re.sub(r"\s+", " ", label_text).strip().lower()
    for label in FIELD_ORDER:
        if simplified == label.lower():
            return label
    return re.sub(r"\s+", " ", label_text).strip()

def parse_fields(text: str):
    matches = list(LABEL_PATTERN.finditer(text))
    rows = []
    seen = set()

    for i, m in enumerate(matches):
        label = canonical_label(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = clean_answer(text[start:end])

        # suppress obvious section headers and blank placeholders
        if answer in {"", "$0.00", "$ 0.00"}:
            continue
        if label in EXCLUDE_LABELS:
            continue

        row = f"- {label}: {answer}"
        if row not in seen:
            seen.add(row)
            rows.append(row)
    return rows

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/parse")
async def parse(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    content = await file.read()
    text = extract_pdf_text(content)
    rows = parse_fields(text)
    return JSONResponse({"rows": rows})
