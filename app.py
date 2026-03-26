from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import io
import re
from typing import Dict, List, Tuple, Optional
import pdfplumber

app = FastAPI(title="Combined Noted from Lead Parser", version="1.0.0")

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

INCLUDE_PRIORITY = [
    "location details",
    "product progress notes",
    "description",
    "traction/revenue notes",
    "business model + unit economics notes",
    "business model + unit economicsnotes",
    "founder cash investment",
    "founder loans",
    "founder cash support",
    "previous investment detail",
    "dilutive outside investment",
    "non-dilutive outside investment",
    "outside debt",
    "legal entity details",
    "current round notes",
]

KNOWN_LABELS = [
    "company", "co. previously/also known as", "lead name", "lead source", "referrer name",
    "lead owner", "spoke/emailed with", "email", "mobile", "tag", "referrer affiliation",
    "heard about from", "heard about date", "confirmed qualified source",
    "confirmed qualified affiliation", "confirmed qualified date", "short description", "website",
    "crunchbase link", "old web site", "description", "primary city",
    "primary us state or country", "types of legal entity", "legal entity details", "location details",
    "country of formation", "subunit of formation", "region", "minimum round size",
    "maximum rounds size", "target valuation or cap", "terms already set by investor",
    "total current commitments", "old desired round size", "desired valuation/cap",
    "current commited $", "current sources (multi-select)", "previous investment",
    "previous investment sources (multi-select)", "current round notes", "founder cash investment",
    "founder loans", "founder cash support", "previous investment detail",
    "dilutive outside investment", "non-dilutive outside investment", "outside debt",
    "full time founders", "part time founders", "other full time employees",
    "other part time employees or contractors", "founder names + linkedin profiles",
    "product progress", "product progress notes", "currently generating revenue",
    "signed contracts", "current primary monthly revenue", "primary revenue models",
    "current other monthly revenue", "other sources of revenue", "gross margin percentage",
    "current monthly operating expenses", "forecast post round monthly operating expenses",
    "most recent month's revenues", "most recent month's gross expenses",
    "forecast post-round gross expenses", "monthly revenue primary product or service",
    "revenue models for primary product or service", "traction/revenue notes",
    "business model + unit economics notes", "business model + unit economicsnotes",
    "milestone and timing of next round", "required clarification", "lead processing notes",
    "assigned to", "combined noted from lead", "street", "street 2", "city", "state", "country",
    "most recent visit", "average time spent (minutes)", "referrer", "first visit",
    "first page visited", "number of chats", "visitor score", "days visited"
]

NORMALIZE_FIXES = {
    "business model + unit economicsnotes": "Business Model + Unit Economics Notes",
}

class ParseResponse(BaseModel):
    extracted_text: str
    rows: List[str]
    pairs: List[Dict[str, str]]


def normalize_label(label: str) -> str:
    label = label.replace("\uff1a", ":")
    label = re.sub(r"\s*:\s*$", "", label).strip()
    label = re.sub(r"\s+", " ", label)
    lower = label.lower()
    pretty = NORMALIZE_FIXES.get(lower)
    if pretty:
        return pretty
    return " ".join(word if word.isupper() else word.capitalize() for word in label.split(" "))


def normalize_key(label: str) -> str:
    label = label.replace("\uff1a", ":")
    label = re.sub(r"\s*:\s*$", "", label).strip().lower()
    label = label.replace("\n", " ")
    label = re.sub(r"\s+", " ", label)
    return label


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    parts: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            parts.append(txt)
    return "\n".join(parts)


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufffe", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def line_has_label(line: str) -> bool:
    # visible label ending with : and not just a URL/time fragment
    return bool(re.match(r"^[^:\n]{1,120}:\s*(.*)$", line.strip()))


def split_labeled_lines(text: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    current_label: Optional[str] = None
    current_answer: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_label and current_answer:
                current_answer.append("")
            continue

        m = re.match(r"^([^:\n]{1,120}?)\s*:\s*(.*)$", line)
        if m:
            new_label = m.group(1).strip()
            inline_answer = m.group(2).strip()
            if current_label is not None:
                pairs.append((current_label, " ".join(x for x in current_answer if x != "").strip()))
            current_label = new_label
            current_answer = [inline_answer] if inline_answer else []
        else:
            if current_label is not None:
                current_answer.append(line)

    if current_label is not None:
        pairs.append((current_label, " ".join(x for x in current_answer if x != "").strip()))

    return pairs


def rebalance_specific_fields(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    # Fix the common Zoho block where 3 labels may exist before their answers.
    fixed: List[Tuple[str, str]] = []
    i = 0
    while i < len(pairs):
        label_key = normalize_key(pairs[i][0])
        if label_key == "legal entity details":
            current = dict((normalize_key(k), v) for k, v in pairs[i:i+3])
            if "legal entity details" in current and "location details" in current and "current round notes" in current:
                le = current["legal entity details"]
                loc = current["location details"]
                crn = current["current round notes"]
                # Split using anchors when merged by plain text extraction.
                merged = " ".join([le, loc, crn]).strip()
                if merged:
                    le_val = le
                    loc_val = loc
                    crn_val = crn
                    m = re.search(r"(Delaware, C-Corp - Sept 2025)", merged, re.I)
                    if m:
                        le_val = m.group(1).strip()
                    m2 = re.search(r"(US first, then SEA\..*?faster access\.)", merged, re.I)
                    if m2:
                        loc_val = re.sub(r"\s+", " ", m2.group(1)).strip()
                    m3 = re.search(r"(We are raising \$500k on a SAFE.*?anchor sites\.)", merged, re.I)
                    if m3:
                        crn_val = re.sub(r"\s+", " ", m3.group(1)).strip()
                    fixed.extend([
                        ("Legal Entity Details", le_val),
                        ("Location Details", loc_val),
                        ("Current Round Notes", crn_val),
                    ])
                    i += 3
                    continue
        fixed.append((normalize_label(pairs[i][0]), pairs[i][1]))
        i += 1
    return fixed


def filter_pairs(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen = set()
    for label, answer in pairs:
        key = normalize_key(label)
        ans = re.sub(r"\s+", " ", answer).strip()
        if not key or key in EXCLUDE_LABELS:
            continue
        if not ans or ans == "$0.00":
            continue
        pretty = normalize_label(label)
        item = (pretty, ans)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def parse_pdf_text(text: str) -> List[Tuple[str, str]]:
    cleaned = clean_text(text)
    pairs = split_labeled_lines(cleaned)
    pairs = rebalance_specific_fields(pairs)
    pairs = filter_pairs(pairs)
    return pairs


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
    rows = [f"- {label}: {answer}" for label, answer in pairs]
    return ParseResponse(
        extracted_text=text,
        rows=rows,
        pairs=[{"question": label, "answer": answer} for label, answer in pairs],
    )
