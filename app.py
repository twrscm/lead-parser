from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import io
import re
from typing import Dict, List, Tuple
import pdfplumber

app = FastAPI(title="Combined Noted from Lead Parser", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXCLUDE_LABELS = {
    "review decision date",
    "lead status",
    "lead grade",
    "created by",
    "modified by",
    "generated email",
    "company",
    "lead name",
    "lead source",
    "lead owner",
    "spoke/emailed with",
    "email",
    "mobile",
    "website",
}

KNOWN_LABELS = [
    "Company", "Co. Previously/Also Known As", "Lead Name", "Lead Source", "Referrer Name",
    "Lead Owner", "Spoke/Emailed With", "Email", "Mobile", "Tag", "Referrer Affiliation",
    "Heard About From", "Heard About Date", "Confirmed Qualified Source",
    "Confirmed Qualified Affiliation", "Confirmed Qualified Date", "Short Description", "Website",
    "CrunchBase Link", "Old Web Site", "Description", "Primary City",
    "Primary US State or Country", "Types of Legal Entity", "Legal Entity Details", "Location Details",
    "Country of Formation", "Subunit of Formation", "Region", "Minimum Round Size",
    "Maximum Rounds Size", "Target Valuation or Cap", "Terms Already Set By Investor",
    "Total Current Commitments", "Old Desired Round Size", "Desired Valuation/Cap",
    "Current Commited $", "Current Sources (multi-select)", "Previous Investment",
    "Previous Investment Sources (multi-select)", "Current Round Notes", "Founder Cash Investment",
    "Founder Loans", "Founder Cash Support", "Previous Investment Detail",
    "Dilutive Outside Investment", "Non-Dilutive Outside Investment", "Outside Debt",
    "Full Time Founders", "Part Time Founders", "Other Full Time Employees",
    "Other Part Time Employees or Contractors", "Founder Names + LinkedIn Profiles",
    "Product Progress", "Product Progress Notes", "Currently Generating Revenue",
    "Signed Contracts", "Current Primary Monthly Revenue", "Primary Revenue Models",
    "Current Other Monthly Revenue", "Other Sources of Revenue", "Gross Margin Percentage",
    "Current Monthly Operating Expenses", "Forecast Post Round Monthly Operating Expenses",
    "Most Recent Month's Revenues", "Most Recent Month's Gross Expenses",
    "Forecast Post-Round Gross Expenses", "Monthly Revenue Primary Product or Service",
    "Revenue Models for Primary Product or Service", "Traction/Revenue Notes",
    "Business Model + Unit Economics Notes", "Business Model + Unit EconomicsNotes",
    "Milestone and Timing of Next Round", "Required Clarification", "Lead Processing Notes",
    "Assigned To", "Combined Noted from Lead", "Street", "Street 2", "City", "State", "Country",
    "Most Recent Visit", "Average Time Spent (Minutes)", "Referrer", "First Visit",
    "First Page Visited", "Number Of Chats", "Visitor Score", "Days Visited",
]

PRETTY_LABELS = {
    "business model + unit economicsnotes": "Business Model + Unit Economics Notes",
}

class ParseResponse(BaseModel):
    extracted_text: str
    rows: List[str]
    pairs: List[Dict[str, str]]


def normalize_key(label: str) -> str:
    label = label.replace("\uff1a", ":")
    label = re.sub(r"\s*:\s*$", "", label)
    label = re.sub(r"\s+", " ", label.strip())
    return label.lower()


def pretty_label(label: str) -> str:
    key = normalize_key(label)
    if key in PRETTY_LABELS:
        return PRETTY_LABELS[key]
    return label.strip().rstrip(":") + ":"


def clean_extracted_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\ufffe", "")
    text = text.replace("\r", "\n")
    # fix wrapped known labels that often split across lines
    text = re.sub(r"Business\s+Model\s+\+\s+Unit\s+Economics\s*\n\s*Notes\s*:", "Business Model + Unit Economics Notes :", text, flags=re.I)
    text = re.sub(r"Current\s+Monthly\s+Operating\s*\n\s*Expenses\s*:", "Current Monthly Operating Expenses :", text, flags=re.I)
    text = re.sub(r"Forecast\s+Post\s+Round\s+Monthly\s*\n\s*Operating\s+Expenses\s*:", "Forecast Post Round Monthly Operating Expenses :", text, flags=re.I)
    text = re.sub(r"Most\s+Recent\s+Month's\s+Gross\s*\n\s*Expenses\s*:", "Most Recent Month's Gross Expenses :", text, flags=re.I)
    text = re.sub(r"Forecast\s+Post-Round\s+Gross\s*\n\s*Expenses\s*:", "Forecast Post-Round Gross Expenses :", text, flags=re.I)
    text = re.sub(r"Monthly\s+Revenue\s+Primary\s+Product\s+or\s*\n\s*Service\s*:", "Monthly Revenue Primary Product or Service :", text, flags=re.I)
    text = re.sub(r"Revenue\s+Models\s+for\s+Primary\s+Product\s*\n\s*or\s+Service\s*:", "Revenue Models for Primary Product or Service :", text, flags=re.I)
    text = re.sub(r"Other\s+Part\s+Time\s+Employees\s+or\s*\n\s*Contractors\s*:", "Other Part Time Employees or Contractors :", text, flags=re.I)
    text = re.sub(r"Primary\s+US\s+State\s+or\s+Country\s*:", "Primary US State or Country :", text, flags=re.I)
    # normalize spaces around colons for matching
    text = re.sub(r"\s+:", " :", text)
    return text


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    parts: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            parts.append(txt)
    return "\n".join(parts)


def build_label_pattern() -> re.Pattern:
    def flex(label: str) -> str:
        bits = re.split(r"(\s+)", re.escape(label))
        out = []
        for b in bits:
            if not b:
                continue
            if re.fullmatch(r"\\\s\+", b):
                out.append(r"\s+")
            else:
                out.append(b)
        return "".join(out)
    labels = sorted(KNOWN_LABELS, key=len, reverse=True)
    alt = "|".join(flex(x) for x in labels)
    return re.compile(rf"(?P<label>{alt})\s*:\s*", re.I)


LABEL_PATTERN = build_label_pattern()


def parse_pdf_text(text: str) -> List[Tuple[str, str]]:
    text = clean_extracted_text(text)
    matches = list(LABEL_PATTERN.finditer(text))
    pairs: List[Tuple[str, str]] = []
    for i, m in enumerate(matches):
        raw_label = m.group("label")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = text[start:end]
        answer = re.sub(r"\s+", " ", answer).strip()
        key = normalize_key(raw_label)
        if key in EXCLUDE_LABELS:
            continue
        if not answer or answer == "$0.00":
            continue
        pairs.append((pretty_label(raw_label), answer))

    # de-dupe while keeping order
    seen = set()
    out: List[Tuple[str, str]] = []
    for label, answer in pairs:
        item = (normalize_key(label), answer)
        if item in seen:
            continue
        seen.add(item)
        out.append((label, answer))
    return out


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/parse", response_model=ParseResponse)
async def parse(file: UploadFile = File(...)) -> ParseResponse:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    data = await file.read()
    text = extract_text_from_pdf(data)
    pairs = parse_pdf_text(text)
    rows = [f"- {label} {answer}" if not label.endswith(":") else f"- {label} {answer}" for label, answer in pairs]
    return ParseResponse(
        extracted_text=text,
        rows=rows,
        pairs=[{"question": label.rstrip(':'), "answer": answer} for label, answer in pairs],
    )
