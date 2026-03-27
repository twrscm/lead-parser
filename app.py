from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests
import pdfplumber
import io
import re

app = FastAPI()

EXCLUDE_LABELS = {
    "Review Decision Date","Lead Status","Lead Grade","Created By","Modified By","Generated Email",
    "Company","Lead Name","Lead Source","Lead Owner","Spoke/Emailed With","Email","Mobile","Website",
}

FIELD_ORDER = [
    "Legal Entity Details","Location Details","Description","Product Progress Notes",
    "Traction/Revenue Notes","Business Model + Unit Economics Notes",
    "Founder Cash Investment","Founder Loans","Founder Cash Support",
    "Previous Investment Detail","Dilutive Outside Investment",
    "Non-Dilutive Outside Investment","Outside Debt","Current Round Notes"
]

LABEL_PATTERN = re.compile(
    r"(" + "|".join([re.escape(x).replace(r"\ ", r"\s+") for x in FIELD_ORDER]) + r")\s*:",
    re.IGNORECASE,
)

def clean(text):
    return re.sub(r"\s+", " ", text).strip()

def extract_text(pdf_bytes):
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            out.append(p.extract_text() or "")
    return "\n".join(out)

def parse(text):
    matches = list(LABEL_PATTERN.finditer(text))
    rows = []
    for i, m in enumerate(matches):
        label = m.group(1)
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        answer = clean(text[start:end])

        if not answer or answer == "$0.00":
            continue
        if label in EXCLUDE_LABELS:
            continue

        rows.append(f"- {label}: {answer}")

    return rows

@app.post("/parse")
async def parse_pdf(req: Request):
    body = await req.json()

    refs = body.get("openaiFileIdRefs", [])
    if not refs:
        return {"rows": [], "error": "No file"}

    ref = refs[0]
    link = ref.get("download_link")

    if not link:
        return {"rows": [], "error": "No download link"}

    try:
        r = requests.get(link)
        pdf_bytes = r.content
    except:
        return {"rows": [], "error": "Download failed"}

    text = extract_text(pdf_bytes)
    rows = parse(text)

    return {"rows": rows}
