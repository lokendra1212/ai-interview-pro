import re
from pathlib import Path

SKILLS = ["Python","SQL","JavaScript","TypeScript","React","Node.js","FastAPI","Flask","Django","Machine Learning","Deep Learning","scikit-learn","TensorFlow","PyTorch","Pandas","NumPy","NLP","Generative AI","AWS","Azure","Docker","PostgreSQL","MongoDB","Git","REST API","Data Science","Power BI","Tableau","Java","C++"]

def parse_resume(filename: str, data: bytes):
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    elif ext == ".docx":
        from docx import Document
        import io
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs)
    elif ext == ".txt": text = data.decode("utf-8", errors="replace")
    else: raise ValueError("Upload a PDF, DOCX, or TXT resume.")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text: raise ValueError("No readable text found. This may be a scanned PDF; OCR is not configured.")
    low = text.lower()
    skills = [s for s in SKILLS if re.search(r"(?<![\w])" + re.escape(s.lower()) + r"(?![\w])", low)]
    projects = []
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 25]
    in_projects = False
    for line in text.splitlines():
        if re.search(r"projects?|experience|work history", line, re.I): in_projects = True; continue
        if in_projects and len(line.strip()) > 30: projects.append(line.strip()[:240])
        if len(projects) >= 5: break
    education = [line.strip() for line in text.splitlines() if re.search(r"bachelor|master|university|college|degree|b\.tech|m\.tech", line, re.I)][:5]
    experience_lines=[]; in_experience=False
    for line in text.splitlines():
        if re.search(r"experience|employment|work history", line, re.I): in_experience=True; continue
        if re.search(r"education|projects?|skills|certifications?", line, re.I): in_experience=False
        if in_experience and len(line.strip())>18: experience_lines.append(line.strip()[:240])
        if len(experience_lines)>=5: break
    return {"text":text,"skills":skills,"projects":projects,"education":education,"experience_lines":experience_lines}
