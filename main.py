import os
import json
import subprocess
import re
import logging
from jinja2 import Template
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pyppeteer import launch
from pydantic import BaseModel, EmailStr, Field
from typing import List, Dict, Any, Optional
from markupsafe import escape

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class OtherQualification(BaseModel):
    name: str = ""
    institution: str = ""
    grade: str = ""
    year: str = ""
    grading_system: str = "Percentage"

class StudentData(BaseModel):
    studentinfo: List[Dict[str, Any]] = []
    studentname: str = Field(..., min_length=1, max_length=100)
    qualification_type: str = Field(..., pattern=r"^(SSC|Intermediate|Engineering|Medicine|Law|Arts|Science|Commerce|Diploma|Vocational|Other)$")
    program_name: str = ""
    studentemail: Optional[EmailStr] = ""
    studentmobilenumber: Optional[str] = Field("", pattern=r"^\+?\d{10,15}$|^$")
    studentaddress: str = ""
    city: str = ""
    dob: str = ""
    fathername: str = ""
    fatheroccupation: str = ""
    mothername: str = ""
    motheroccupation: str = ""
    degreeinfo: List[Dict[str, str]] = []
    degreecollege: str = ""
    degreeyearofpass: str = ""
    degree_grading_system: str = "CGPA"
    intercollegename: str = ""
    interboard: str = ""
    interpercentage: str = ""
    interyearofpass: str = ""
    inter_grading_system: str = "Percentage"
    sscschoolname: str = ""
    sscboard: str = ""
    sscgpa: str = ""
    sscyearofpass: str = ""
    ssc_grading_system: str = "CGPA"
    other_qualifications: List[OtherQualification] = []
    skillset: List[str] = []
    projectinfo: List[Dict[str, str]] = []
    experienceinfo: List[Dict[str, Any]] = []
    coursecertification: List[Dict[str, str]] = []
    language: List[str] = []
    linkedin: Optional[str] = None

    class Config:
        extra = "allow"

    @staticmethod
    def ensure_list(v):
        return v if isinstance(v, list) else []

try:
    with open("resume_template.html", "r", encoding="utf-8") as f:
        template_content = f.read()
        template = Template(template_content)
except FileNotFoundError:
    logger.error("resume_template.html not found")
    raise SystemExit(1)

async def init_browser():
    try:
        return await launch(
            executablePath=os.environ.get('PYPPETEER_EXECUTABLE_PATH', r'C:\Program Files\chrome-win\chrome.exe'),  # Fallback path
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu'
            ]
        )
    except Exception as e:
        logger.error(f"Browser initialization failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize browser")
async def generate_pdf(page, html_content):
    await page.setContent(html_content)
    await page.waitForSelector("body")
    return await page.pdf({
        'printBackground': True,
        'format': 'A4',
        #'margin': {'top': '20mm', 'right': '20mm', 'bottom': '20mm', 'left': '20mm'},
        'preferCSSPageSize': True
    })

def format_address(address: str, city: str) -> str:
    if not address and not city:
        return ""
    if address.endswith(city):
        return address
    return f"{address}, {city}" if address else city

def clean_objective(text: str) -> str:
    unwanted_prefixes = [
        r"Here is a possible.*?:",
        r"Here is a short, professional resume objective:",
        r"Resume objective:",
        r"Objective:",
        r"Here is the resume objective:",
        r"Here is a possible",
        r"\*.*?\*",
        r"\n+"
    ]
    for prefix in unwanted_prefixes:
        text = re.sub(prefix, "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    # Ensure the objective starts with a professional phrase
    if not text.startswith(("To ", "Seeking ", "Aiming ")):
        text = f"To {text[0].lower()}{text[1:]}"
    return text

def calculate_average_grade(grades: List[str], grading_system: str) -> str:
    if not grades:
        return "N/A"
    try:
        valid_grades = [float(g) for g in grades if g]
        if not valid_grades:
            return "N/A"
        avg = sum(valid_grades) / len(valid_grades)
        if grading_system == "Marks":
            return f"{int(avg)}"
        return f"{avg:.2f}"
    except Exception as e:
        logger.error(f"Error calculating average grade: {e}")
        return "N/A"

@app.on_event("startup")
async def startup_event():
    app.state.browser = await init_browser()

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.browser.close()

@app.post("/gr")
async def generate_resume_from_json(student_info: List[StudentData]):
    page = None
    try:
        if not student_info or len(student_info) == 0:
            raise HTTPException(status_code=400, detail="Empty student data list")

        student_data = student_info[0].dict()
        student_name = student_data.get("studentname", "UnknownStudent")
        city = student_data.get("city", "")
        safe_student_name = student_name.replace(" ", "_")
        logger.info(f"Generating resume for {student_name}")

        # Calculate average grade for relevant qualifications
        if student_data.get("qualification_type") in ["Engineering", "Arts", "Science", "Commerce"] and student_data.get("degreeinfo"):
            grades = [d.get("grade", "") for d in student_data["degreeinfo"]]
            student_data["degreeavggrade"] = calculate_average_grade(grades, student_data.get("degree_grading_system", "CGPA"))
        else:
            student_data["degreeavggrade"] = "N/A"

        # Generate resume objective
        qual_type = student_data.get("qualification_type", "")
        program_name = student_data.get("program_name", qual_type)
        qual_details = ""
        if qual_type in ["Engineering", "Arts", "Science", "Commerce"]:
            qual_details = f"{program_name}, {student_data.get('degreecollege', '')} ({student_data.get('degreeyearofpass', '')}, {student_data.get('degree_grading_system', 'CGPA')}: {student_data.get('degreeavggrade', '')})"
        elif qual_type in ["Medicine", "Law"]:
            qual_details = f"{program_name}, {student_data.get('degreecollege', '')} ({student_data.get('degreeyearofpass', '')}, {student_data.get('degree_grading_system', 'Percentage')}: {student_data.get('interpercentage', '')})"
        elif qual_type == "Intermediate":
            qual_details = f"{student_data.get('intercollegename', '')} ({student_data.get('interyearofpass', '')}, {student_data.get('inter_grading_system', 'Percentage')}: {student_data.get('interpercentage', '')})"
        elif qual_type == "SSC":
            qual_details = f"{student_data.get('sscschoolname', '')} ({student_data.get('sscyearofpass', '')}, {student_data.get('ssc_grading_system', 'CGPA')}: {student_data.get('sscgpa', '')})"
        elif qual_type in ["Diploma", "Vocational", "Other"] and student_data.get("other_qualifications"):
            qual_details = f"{student_data['other_qualifications'][0].get('name', '')} ({student_data['other_qualifications'][0].get('year', '')}, {student_data['other_qualifications'][0].get('grading_system', 'Percentage')}: {student_data['other_qualifications'][0].get('grade', '')})"

        prompt = f"""
            Write a short, professional resume objective in 2-3 sentences for a candidate applying for an entry-level position. Base it strictly on the following details:
            Name: {student_data.get('studentname', '')}
            Highest Qualification: {qual_details}
            Skills: {", ".join([s for s in student_data.get('skillset', []) if s.strip()])}
            Projects: {", ".join([p.get('name', '') for p in student_data.get('projectinfo', []) if p.get('name', '').strip()])}
            Experience: {", ".join([exp.get('company', '') for exp in student_data.get('experienceinfo', []) if exp.get('company', '').strip()])}

            Start the objective directly. Do NOT include any introductory phrases like "Here is a possible" or "Resume objective:". Return ONLY the objective text.
        """

        result = subprocess.run(
            ["ollama", "run", "llama3", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )

        if result.returncode != 0:
            logger.error(f"Ollama error: {result.stderr}")
            objective = f"To leverage my skills in {', '.join([s for s in student_data.get('skillset', ['N/A']) if s.strip()] or ['N/A'])} and academic foundation in {program_name} to secure an entry-level position where I can contribute to innovative projects and grow professionally."
        else:
            objective = clean_objective(result.stdout.strip())

        student_data["objective"] = objective if objective else f"To leverage my skills in {', '.join([s for s in student_data.get('skillset', ['N/A']) if s.strip()] or ['N/A'])} and academic foundation in {program_name} to secure an entry-level position where I can contribute to innovative projects and grow professionally."
        lang = ", ".join([l for l in student_data.get("language", []) if l.strip()])

        address = student_data.get("studentaddress", "")
        formatted_address = format_address(address, city)

        # Filter non-empty entries
        formatted_skillset = [s for s in student_data.get("skillset", []) if s.strip()]
        formatted_language = [l for l in student_data.get("language", []) if l.strip()]
        formatted_certifications = [
            cert.get('newCertification', '')
            for cert in student_data.get('coursecertification', [])
            if cert.get('newCertification', '').strip()
        ]
        formatted_projects = [
            {"name": p.get("name", ""), "description": p.get("description", "")}
            for p in student_data.get("projectinfo", [])
            if p.get("name", "").strip() or p.get("description", "").strip()
        ]
        formatted_experience = [
            {"company": exp.get("company", ""), "years": exp.get("years", "")}
            for exp in student_data.get("experienceinfo", [])
            if exp.get("company", "").strip() or exp.get("years", "").strip()
        ]
        formatted_other_qualifications = [
            {
                "name": qual.get("name", ""),
                "institution": qual.get("institution", ""),
                "grade": qual.get("grade", ""),
                "year": qual.get("year", ""),
                "grading_system": qual.get("grading_system", "Percentage")
            }
            for qual in student_data.get("other_qualifications", [])
            if qual.get("name", "").strip() or qual.get("institution", "").strip()
        ]
        formatted_degreeinfo = [
            {"grade": d.get("grade", "")}
            for d in student_data.get("degreeinfo", [])
            if d.get("grade", "").strip()
        ]

        data_for_template = {
            "studentname": escape(student_data.get("studentname", "")),
            "qualification_type": escape(student_data.get("qualification_type", "")),
            "program_name": escape(student_data.get("program_name", "")),
            "studentmobilenumber": escape(student_data.get("studentmobilenumber", "")),
            "studentemail": escape(student_data.get("studentemail", "")),
            "studentaddress": escape(formatted_address) if formatted_address else "",
            "city": escape(city),
            "objective": escape(student_data.get("objective", "")),
            "degreecollege": escape(student_data.get("degreecollege", "")),
            "degreeyearofpass": escape(student_data.get("degreeyearofpass", "")),
            "degreeavggrade": escape(student_data.get("degreeavggrade", "")),
            "degree_grading_system": escape(student_data.get("degree_grading_system", "CGPA")),
            "degreeinfo": formatted_degreeinfo,
            "intercollegename": escape(student_data.get("intercollegename", "")),
            "interboard": escape(student_data.get("interboard", "")),
            "interpercentage": escape(student_data.get("interpercentage", "")),
            "interyearofpass": escape(student_data.get("interyearofpass", "")),
            "inter_grading_system": escape(student_data.get("inter_grading_system", "Percentage")),
            "sscschoolname": escape(student_data.get("sscschoolname", "")),
            "sscboard": escape(student_data.get("sscboard", "")),
            "sscgpa": escape(student_data.get("sscgpa", "")),
            "sscyearofpass": escape(student_data.get("sscyearofpass", "")),
            "ssc_grading_system": escape(student_data.get("ssc_grading_system", "CGPA")),
            "other_qualifications": formatted_other_qualifications,
            "skillset": [escape(s) for s in formatted_skillset],
            "projectinfo": [
                {"name": escape(p["name"]), "description": escape(p["description"])}
                for p in formatted_projects
            ],
            "experienceinfo": [
                {"company": escape(exp["company"]), "years": escape(exp["years"])}
                for exp in formatted_experience
            ],
            "certifications": [escape(cert) for cert in formatted_certifications],
            "dob": escape(student_data.get("dob", "")),
            "fathername": escape(student_data.get("fathername", "")),
            "fatheroccupation": escape(student_data.get("fatheroccupation", "")),
            "mothername": escape(student_data.get("mothername", "")),
            "motheroccupation": escape(student_data.get("motheroccupation", "")),
            "language": escape(lang) if lang else "",
            "linkedin": escape(student_data.get("linkedin", ""))  # Added LinkedIn field
        }

        page = await app.state.browser.newPage()
        html_content = template.render(student_info=data_for_template)
        pdf_bytes = await generate_pdf(page, html_content)

        base_path = os.path.join(os.getcwd(), "resumes")
        os.makedirs(base_path, exist_ok=True)
        pdf_filename = f"Resume_{safe_student_name}.pdf"
        pdf_path = os.path.join(base_path, pdf_filename)

        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)

        return FileResponse(
            path=pdf_path,
            media_type='application/pdf',
            filename=pdf_filename
        )

    except Exception as e:
        logger.error(f"Error generating resume: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if page is not None:
            await page.close()