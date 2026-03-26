
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import pdfplumber
import re
import io

app = FastAPI(title="Combined Noted from Lead Parser", version="3.0.0")

EXCLUDE_LABELS = {
    "Review Decision Date","Lead Status","Lead Grade","Created By","Modified By",
    "Generated Email","Company","Lead Name","Lead Source","Lead Owner","Spoke/Emailed With",
    "Email","Mobile","Website"
}

FIELD_ORDER = [
    "Company","Co. Previously/Also Known As","Lead Name","Lead Source","Referrer Name","Lead Owner","Spoke/Emailed With",
    "Email","Mobile","Tag","Referrer Affiliation","Heard About From","Heard About Date","Confirmed Qualified Source",
    "Confirmed Qualified Affiliation","Confirmed Qualified Date","Short Description","Website","CrunchBase Link","Old Web Site",
    "Description","Primary City","Primary US State or Country","Types of Legal Entity","Legal Entity Details","Location Details",
    "Country of Formation","Subunit of Formation","Region","Minimum Round Size","Maximum Rounds Size","Target Valuation or Cap",
    "Terms Already Set By Investor","Total Current Commitments","Old Desired Round Size","Desired Valuation/Cap","Current Commited $",
    "Current Sources (multi-select)","Previous Investment","Previous Investment Sources (multi-select)","Current Round Notes",
    "Founder Cash Investment","Founder Loans","Founder Cash Support","Previous Investment Detail","Dilutive Outside Investment",
    "Non-Dilutive Outside Investment","Outside Debt","Full Time Founders","Part Time Founders","Other Full Time Employees",
    "Other Part Time Employees or Contractors","Founder Names + LinkedIn Profiles","Product Progress","Product Progress Notes",
    "Currently Generating Revenue","Signed Contracts","Current Primary Monthly Revenue","Primary Revenue Models",
    "Current Other Monthly Revenue","Other Sources of Revenue","Gross Margin Percentage","Current Monthly Operating Expenses",
    "Forecast Post Round Monthly Operating Expenses","Most Recent Month's Revenues","Most Recent Month's Gross Expenses",
    "Forecast Post-Round Gross Expenses","Monthly Revenue Primary Product or Service","Revenue Models for Primary Product or Service",
    "Traction/Revenue Notes","Business Model + Unit Economics Notes","Milestone and Timing of Next Round","Review Decision Date",
    "Required Clarification","Lead Status","Lead Grade","Lead Processing Notes","Assigned To","Created By","Modified By",
    "Combined Noted from Lead","Generated Email","Street","Street 2","City","State","Country","Most Recent Visit",
    "Average Time Spent (Minutes)","Referrer","First Visit","First Page Visited","Number Of Chats","Visitor Score","Days Visited"
]
HEADINGS = {
    "Lead Information","New Lead Information","Startup Overview","New Startup Overview","Old Startup Overview",
    "Extended Description and Notes","Old Location","New Location","New Potential Deal Overview","Old Potential Deal Overview",
    "Potential Deal Details","New Previous Investment","New Founders and Employees","Old Founders and Employee","Founder Detail",
    "Progress Overview","New Financials Overview","Old Financials Overview","Progress and Financial Detail","Next Round",
    "Evaluation Workflow","Address","Visit Summary","Cadences","Attachments","Products","Open Activities","Closed Activities",
    "Invited Meetings","Emails","Zoho Survey","Zoho Desk","Notes","No records found","Combined Noted from Lead"
}

def normalize(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\ufffe", "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r'[ \t]+', ' ', text)
    return text

def clean_answer(text: str) -> str:
    text = normalize(text)
    text = re.sub(r'\s*\n\s*', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if text in HEADINGS:
        return ""
    if re.fullmatch(r'.+:\s*', text):
        return ""
    for h in HEADINGS:
        if text.endswith(" " + h):
            text = text[:-(len(h)+1)].strip()
        if text.startswith(h + " "):
            text = text[(len(h)+1):].strip()
    return text

def extract_layout_text(pdf_bytes: bytes) -> str:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(normalize(page.extract_text(layout=True) or ""))
    return "\n".join(pages)

def same_line_extract(layout_text: str):
    fields = {}
    label_re = re.compile(r'([A-Za-z0-9/\'+().&,$ -]+?)\s*:')
    for raw_line in layout_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.strip() in HEADINGS:
            continue
        matches = list(label_re.finditer(line))
        if not matches:
            continue
        for i, m in enumerate(matches):
            label = m.group(1).strip()
            if label not in FIELD_ORDER:
                continue
            nxt = matches[i+1].start() if i + 1 < len(matches) else len(line)
            ans = clean_answer(line[m.end():nxt])
            if ans:
                fields[label] = ans
            else:
                fields.setdefault(label, fields.get(label, ""))
    return fields

def section_extract(layout_text: str, fields: dict):
    flat = normalize(layout_text)

    rules = [
        ("Short Description", r"Short Description\s*:\s*(.*?)\s+New Startup Overview"),
        ("Description", r"Description\s*:\s*(.*?)\s+Old Location"),
        ("Legal Entity Details", r"Legal Entity Details\s*:\s*(.*?)\s+Subunit of Formation"),
        ("Location Details", r"Location Details\s*:\s*(.*?)\s+New Potential Deal Overview"),
        ("Current Round Notes", r"Current Round Notes\s*:\s*(.*?)\s+New Previous Investment"),
        ("Previous Investment Detail", r"Previous Investment Detail\s*:\s*(.*?)\s+New Founders and Employees"),
        ("Founder Names + LinkedIn Profiles", r"Founder Names \+ LinkedIn Profiles\s*:\s*(.*?)\s+Progress Overview"),
        ("Product Progress Notes", r"Product Progress Notes\s*:\s*(.*?)\s+New Financials Overview"),
        ("Traction/Revenue Notes", r"Traction/Revenue Notes\s*:\s*(.*?)\s+Business Model \+ Unit Economics"),
        ("Business Model + Unit Economics Notes", r"Business Model \+ Unit Economics\s+Notes\s*:\s*(.*?)\s+Next Round"),
    ]
    for label, pattern in rules:
        m = re.search(pattern, flat, re.I | re.S)
        if m:
            fields[label] = clean_answer(m.group(1))

    simple_rules = [
        ("Types of Legal Entity", r"Types of Legal Entity\s*:\s*(.*?)\s+Country of Formation"),
        ("Country of Formation", r"Country of Formation\s*:\s*(.*?)\s+Legal Entity Details"),
        ("Subunit of Formation", r"Subunit of Formation\s*:\s*(.*?)\s+Region"),
        ("Minimum Round Size", r"Minimum Round Size\s*:\s*(\$ ?[0-9,]+\.\d{2})"),
        ("Maximum Rounds Size", r"Maximum Rounds Size\s*:\s*(\$ ?[0-9,]+\.\d{2})"),
        ("Target Valuation or Cap", r"Target Valuation or Cap\s*:\s*(\$ ?[0-9,]+\.\d{2})"),
        ("Founder Loans", r"Founder Loans\s*:\s*(\$ ?[0-9,]+\.\d{2})"),
        ("Full Time Founders", r"Full Time Founders\s*:\s*([0-9]+)"),
        ("Part Time Founders", r"Part Time Founders\s*:\s*([0-9]+)"),
        ("Current Primary Monthly Revenue", r"Current Primary Monthly Revenue\s*:\s*(\$ ?[0-9,]+\.\d{2})"),
        ("Primary Revenue Models", r"Primary Revenue Models\s*:\s*(.*?)\s+Operating Expenses"),
        ("Other Sources of Revenue", r"Other Sources of Revenue\s*:\s*(.*?)\s+Old Financials Overview"),
        ("Gross Margin Percentage", r"Gross Margin Percentage\s*:\s*([0-9]+)"),
        ("Product Progress", r"Product Progress\s*:\s*(.*?)\s+Product Progress Notes"),
    ]
    for label, pattern in simple_rules:
        m = re.search(pattern, flat, re.I | re.S)
        if m:
            fields[label] = clean_answer(m.group(1))

    m = re.search(r"Current Monthly Operating\s+\$ ?([0-9,]+\.\d{2})\s+Expenses\s*:", flat, re.I)
    if m:
        fields["Current Monthly Operating Expenses"] = "$ " + m.group(1)

    m = re.search(r"Forecast Post Round Monthly\s+\$ ?([0-9,]+\.\d{2}).{0,80}?Operating Expenses\s*:", flat, re.I | re.S)
    if m:
        fields["Forecast Post Round Monthly Operating Expenses"] = "$ " + m.group(1)

    return fields

def format_rows(fields: dict):
    rows = []
    seen = set()
    for label in FIELD_ORDER:
        ans = clean_answer(fields.get(label, ""))
        if label in EXCLUDE_LABELS:
            continue
        if not ans or ans in {"$0.00", "$ 0.00"}:
            continue
        row = f"- {label}: {ans}"
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
        raise HTTPException(status_code=400, detail="Please upload a PDF.")
    pdf_bytes = await file.read()
    layout_text = extract_layout_text(pdf_bytes)
    fields = same_line_extract(layout_text)
    fields = section_extract(layout_text, fields)
    rows = format_rows(fields)
    return JSONResponse({"rows": rows, "fields": fields})
