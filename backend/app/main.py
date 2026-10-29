from datetime import datetime, timezone
from pathlib import Path
import json, random, re, time, mimetypes
from urllib.parse import quote
from collections import defaultdict, deque
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc
from .config import settings
from .database import Base, engine, get_db
from .models import User, Resume, Interview
from .security import hash_password, verify_password, create_token, token_user_id
from .questions import BANK, APTITUDE, interview_questions
from .evaluation import evaluate, communication_metrics
from .conversation import interviewer_turn
from .resumes import parse_resume, SKILLS
from .coach import build_coach_plan

Base.metadata.create_all(bind=engine)
app = FastAPI(title="AI Interview Pro API", version="1.0.0", description="Local-first practice interviews with transparent rubric scoring.")
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def current_user(token: str = Depends(oauth), db: Session = Depends(get_db)) -> User:
    try: uid = token_user_id(token)
    except ValueError: raise HTTPException(401, "Invalid or expired sign-in. Please log in again.")
    user = db.get(User, uid)
    if not user: raise HTTPException(401, "Account not found. Please log in again.")
    return user

class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
class LoginBody(BaseModel):
    username: EmailStr
    password: str
class StartBody(BaseModel):
    mode: str = "technical"
    role: str = "Software Engineer"
    job_description: str = Field(default="", max_length=12000)
    topic: str = "All topics"
    difficulty: str = "intermediate"
    count: int = Field(default=5, ge=3, le=12)
    negative_marking: bool = False
    resume_id: int | None = None
    external_ai_consent: bool = False
class AnswerBody(BaseModel):
    question_index: int = Field(ge=0)
    answer: str = Field(max_length=10000)
    duration_seconds: float | None = Field(default=None, ge=0, le=7200)
class AptitudeSubmit(BaseModel):
    selections: dict[str, list[int]]
    duration_seconds: float | None = Field(default=None, ge=0, le=7200)
class SkillUpdate(BaseModel): skills: list[str] = Field(max_length=80)
class ProfileBody(BaseModel): name: str = Field(min_length=1, max_length=100)
class CoachRequest(BaseModel): allow_external_ai: bool = False

_auth_attempts: dict[str, deque[float]] = defaultdict(deque)
def auth_rate_limit(request: Request):
    key=request.client.host if request.client else "unknown"
    now=time.monotonic(); attempts=_auth_attempts[key]
    while attempts and attempts[0] < now-60: attempts.popleft()
    if len(attempts)>=12: raise HTTPException(429,"Too many sign-in attempts. Wait a minute and try again.")
    attempts.append(now)

def user_resume(db: Session, user: User):
    return db.query(Resume).filter(Resume.user_id == user.id).order_by(desc(Resume.created_at)).first()

def public_question(q: dict):
    return {k:v for k,v in q.items() if k not in ("reference","concepts","correct","explanation","negative_marking","external_ai_consent")}

@app.get("/api/health")
def health(): return {"status":"ok","service":"AI Interview Pro","evaluator":"local-rubric+lexical-baseline"}

@app.post("/api/auth/register")
def register(body: RegisterBody, db: Session = Depends(get_db), _limited: None = Depends(auth_rate_limit)):
    email = body.email.lower().strip()
    if db.query(User).filter(User.email == email).first(): raise HTTPException(409, "An account with that email already exists.")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token":create_token(user.id),"token_type":"bearer","user":{"id":user.id,"name":user.name,"email":user.email}}

@app.post("/api/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db), _limited: None = Depends(auth_rate_limit)):
    user = db.query(User).filter(User.email == body.username.lower().strip()).first()
    if not user or not verify_password(body.password, user.password_hash): raise HTTPException(401, "Email or password is incorrect.")
    return {"access_token":create_token(user.id),"token_type":"bearer","user":{"id":user.id,"name":user.name,"email":user.email}}

@app.get("/api/auth/me")
def me(user: User = Depends(current_user)): return {"id":user.id,"name":user.name,"email":user.email}

@app.patch("/api/profile")
def update_profile(body: ProfileBody, user:User=Depends(current_user), db:Session=Depends(get_db)):
    user.name=body.name.strip()
    if not user.name: raise HTTPException(422,"Name cannot be empty.")
    db.commit()
    return {"id":user.id,"name":user.name,"email":user.email}

@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sessions = db.query(Interview).filter(Interview.user_id == user.id).order_by(desc(Interview.created_at)).all()
    # A completed session is only usable for analytics when its persisted report
    # is an object. Older/partial records may contain null optional report data.
    completed = [s for s in sessions if s.status == "completed" and isinstance(s.report, dict)]
    scores = [
        score for s in completed
        if isinstance((score := s.report.get("overall_score")), (int, float))
        and not isinstance(score, bool)
    ]
    skill_sum: dict[str,list[int | float | str]] = {}
    for s in completed:
        skill_scores = s.report.get("skill_scores")
        if not isinstance(skill_scores, list):
            continue
        for item in skill_scores:
            if not isinstance(item, dict) or not isinstance(item.get("skill"), str):
                continue
            name = " ".join(item["skill"].split())
            score = item.get("score")
            if not name or not isinstance(score, (int, float)) or isinstance(score, bool):
                continue
            key = name.casefold()
            if key not in skill_sum:
                skill_sum[key] = [name]
            skill_sum[key].append(score)
    avg = round(sum(scores)/len(scores)) if scores else 0
    summarized_skills = [
        {"skill": values[0], "score": round(sum(values[1:]) / len(values[1:]))}
        for values in skill_sum.values()
    ]
    weakest = sorted(((item["skill"], item["score"]) for item in summarized_skills), key=lambda x:x[1])[:2]

    def valid_duration(value) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return 0
        duration = float(value)
        return duration if 0 < duration <= 7200 else 0

    seconds_total = 0.0
    for session in completed:
        aptitude = session.report.get("aptitude")
        if isinstance(aptitude, dict) and aptitude.get("duration_seconds") is not None:
            # The submitted assessment duration is authoritative; answer records
            # for aptitude sessions intentionally have no individual durations.
            seconds_total += valid_duration(aptitude.get("duration_seconds"))
        elif isinstance(session.answers, list):
            seconds_total += sum(
                valid_duration(answer.get("duration_seconds"))
                for answer in session.answers if isinstance(answer, dict)
            )
    minutes_practiced = int(seconds_total / 60 + 0.5)
    return {"user":{"name":user.name,"email":user.email},"stats":{"completed":len(completed),"average_score":avg,"minutes_practiced":minutes_practiced},"recent":[session_summary(s) for s in sessions[:6]],"skills":summarized_skills,"recommendations":[f"Practice {k}: recent average {v}/100." for k,v in weakest] or ["Start a practice session to get targeted recommendations."],"resume":resume_summary(user_resume(db,user))}

def resume_summary(r: Resume | None):
    if not r: return None
    lines=r.extracted_text.splitlines()
    education=[line.strip() for line in lines if re.search(r"bachelor|master|university|college|degree|b\.tech|m\.tech",line,re.I)][:5]
    experience=[]; in_experience=False
    for line in lines:
        if re.search(r"experience|employment|work history",line,re.I): in_experience=True; continue
        if re.search(r"education|projects?|skills|certifications?",line,re.I): in_experience=False
        if in_experience and len(line.strip())>18: experience.append(line.strip()[:240])
        if len(experience)>=5: break
    return {"id":r.id,"filename":r.filename,"skills":r.skills,"projects":r.projects,"education":education,"experience_lines":experience,"text_preview":r.extracted_text[:1500],"created_at":r.created_at.isoformat(),"file_saved":r.file_data is not None,"file_size_bytes":len(r.file_data) if r.file_data is not None else None}

def session_summary(s: Interview):
    return {"id":s.id,"mode":s.mode,"role":s.role,"difficulty":s.difficulty,"status":s.status,"question_count":len(s.questions),"answered":len(s.answers),"score":s.report.get("overall_score") if s.report else None,"created_at":s.created_at.isoformat()}

@app.post("/api/resumes/upload")
async def upload_resume(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    filename = Path(file.filename or "resume").name
    data = await file.read(settings.max_upload_mb*1024*1024 + 1)
    if len(data) > settings.max_upload_mb*1024*1024: raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB.")
    if Path(filename).suffix.lower() not in {".pdf",".docx",".txt"}: raise HTTPException(415, "Upload a PDF, DOCX, or TXT resume.")
    try: parsed = parse_resume(filename, data)
    except ImportError as e: raise HTTPException(503, f"Resume parser dependency unavailable: {e.name}")
    except Exception as e: raise HTTPException(422, str(e) if isinstance(e,ValueError) else "Could not read this document. Check the file and try again.")
    record = Resume(user_id=user.id, filename=filename, extracted_text=parsed["text"], file_data=data, content_type=file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream", skills=parsed["skills"], projects=parsed["projects"])
    db.add(record); db.commit(); db.refresh(record)
    return {**resume_summary(record),"text_preview":parsed["text"][:1500]}

@app.get("/api/resumes/{resume_id}/download")
def download_resume(resume_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    r=db.query(Resume).filter(Resume.id==resume_id,Resume.user_id==user.id).first()
    if not r: raise HTTPException(404,"Resume not found.")
    if r.file_data is None: raise HTTPException(410,"The original file is unavailable. Upload the resume again to save it.")
    return Response(content=r.file_data,media_type=r.content_type or "application/octet-stream",headers={"Content-Disposition":f"attachment; filename*=UTF-8''{quote(r.filename)}"})

@app.get("/api/resumes/{resume_id}")
def get_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.query(Resume).filter(Resume.id==resume_id,Resume.user_id==user.id).first()
    if not r: raise HTTPException(404,"Resume not found.")
    return resume_summary(r)

@app.patch("/api/resumes/{resume_id}/skills")
def update_resume_skills(resume_id:int, body:SkillUpdate, user:User=Depends(current_user), db:Session=Depends(get_db)):
    r=db.query(Resume).filter(Resume.id==resume_id,Resume.user_id==user.id).first()
    if not r: raise HTTPException(404,"Resume not found.")
    r.skills=list(dict.fromkeys(s.strip()[:80] for s in body.skills if s.strip()))[:80]; db.commit()
    return resume_summary(r)

@app.post("/api/interviews/start")
def start_interview(body: StartBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    allowed_modes={"technical","behavioral","resume","aptitude","mcq","communication","voice"}
    if body.mode not in allowed_modes: raise HTTPException(422,"Choose a supported interview mode.")
    if body.difficulty not in {"beginner","intermediate","advanced"}: raise HTTPException(422,"Choose a supported difficulty.")
    resume = None
    if body.resume_id is not None:
        resume = db.query(Resume).filter(Resume.id==body.resume_id,Resume.user_id==user.id).first()
        if not resume: raise HTTPException(404,"Resume not found.")
    elif body.mode == "resume":
        resume = user_resume(db,user)
        if not resume: raise HTTPException(409,"Upload a resume before starting a resume-based session.")
    skills = resume.skills if resume else []
    if body.mode in {"aptitude","mcq"}:
        pool=[q for q in APTITUDE if q["difficulty"]==body.difficulty] or APTITUDE
        random.shuffle(pool); questions=[{**q} for q in pool[:min(body.count,len(pool))]]
        if body.negative_marking:
            for q in questions: q["negative_marking"] = True
    else:
        questions=interview_questions(body.mode,body.topic,body.difficulty,skills,body.count,resume.projects if resume else None)
        if body.job_description.strip():
            matched=[skill for skill in SKILLS if skill.lower() in body.job_description.lower()][:4]
            focus=", ".join(matched) if matched else body.role
            job_question={"id":"job-focus","topic":"Role alignment","difficulty":body.difficulty,"prompt":f"This {body.role} role emphasizes {focus}. Describe a specific example from your experience that shows how you would contribute in this area.","reference":f"A relevant answer connects experience to {focus}, explains a specific contribution, and gives an outcome.","concepts":["experience","contribution","example","outcome"]+([s.lower() for s in matched[:2]]),"skill":"Role alignment"}
            questions=([job_question]+questions)[:body.count]
    if body.mode == "voice" and questions:
        questions[0]["external_ai_consent"] = body.external_ai_consent
    record=Interview(user_id=user.id,mode=body.mode,role=body.role[:120],difficulty=body.difficulty,questions=questions)
    db.add(record); db.commit(); db.refresh(record)
    return {"id":record.id,"mode":record.mode,"role":record.role,"difficulty":record.difficulty,"questions":[public_question(q) for q in questions],"total":len(questions),"timer_seconds":len(questions)*60}

@app.get("/api/interviews/{interview_id:int}")
def get_interview(interview_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    s=db.query(Interview).filter(Interview.id==interview_id,Interview.user_id==user.id).first()
    if not s: raise HTTPException(404,"Interview not found.")
    return {**session_summary(s),"questions":[public_question(q) for q in s.questions],"answers":s.answers,"report":s.report}

@app.post("/api/interviews/{interview_id}/submit-answer")
def submit_answer(interview_id:int,body:AnswerBody,user:User=Depends(current_user),db:Session=Depends(get_db)):
    s=db.query(Interview).filter(Interview.id==interview_id,Interview.user_id==user.id).first()
    if not s: raise HTTPException(404,"Interview not found.")
    if s.status!="in_progress": raise HTTPException(409,"This interview is already finished.")
    if body.question_index>=len(s.questions): raise HTTPException(422,"Question index is out of range.")
    prior=next((a for a in s.answers if a["question_index"]==body.question_index),None)
    if prior: raise HTTPException(409,"This question has already been submitted.")
    q=s.questions[body.question_index]
    if s.mode in {"aptitude","mcq"}:
        score=100 if body.answer == str(q["correct"][0]) else 0
        result={"score":score,"breakdown":{"correctness":score},"feedback":q["explanation"],"correct_option":q["correct"][0],"concepts_covered":[],"concepts_missing":[]}
    else: result=evaluate(q,body.answer)
    result["communication"]=communication_metrics(body.answer,body.duration_seconds)
    saved={"question_index":body.question_index,"question":public_question(q),"answer":body.answer,"result":result,"duration_seconds":body.duration_seconds}
    s.answers=s.answers+[saved]; db.commit()
    return saved

@app.post("/api/interviews/{interview_id}/conversation-turn")
def conversation_turn(interview_id:int,body:AnswerBody,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Save and evaluate a spoken/text turn, then decide whether to probe or advance."""
    s=db.query(Interview).filter(Interview.id==interview_id,Interview.user_id==user.id).first()
    if not s: raise HTTPException(404,"Interview not found.")
    if s.mode!="voice": raise HTTPException(409,"Conversational turns are only available in a voice interview.")
    if s.status!="in_progress": raise HTTPException(409,"This interview is already finished.")
    if body.question_index>=len(s.questions): raise HTTPException(422,"Question index is out of range.")
    if any(a.get("question_index")==body.question_index for a in s.answers): raise HTTPException(409,"This question has already been submitted.")
    q=s.questions[body.question_index]
    result=evaluate(q,body.answer)
    result["communication"]=communication_metrics(body.answer,body.duration_seconds)
    saved={"question_index":body.question_index,"question":public_question(q),"answer":body.answer,"result":result,"duration_seconds":body.duration_seconds}
    prior_history=[{"question":a.get("question",{}).get("prompt",""),"answer":a.get("answer",""),"is_follow_up":a.get("question",{}).get("is_follow_up",False)} for a in s.answers]
    turn=interviewer_turn(q,body.answer,result,prior_history,allow_external=bool(s.questions and s.questions[0].get("external_ai_consent")))
    follow_up=turn.get("follow_up_question")
    if follow_up:
        concepts = result.get("concepts_missing", [])[:2]
        if not concepts:
            concepts=["example","result"]
        followup_q={"id":f"voice-followup-{body.question_index}-{len(s.answers)}","topic":q.get("topic","Interview follow-up"),"difficulty":s.difficulty,"prompt":follow_up,"reference":"A useful response adds the requested clarification, example, or outcome and explains its relevance.","concepts":concepts,"skill":q.get("skill",q.get("topic","Communication")),"is_follow_up":True}
        s.questions=s.questions[:body.question_index+1]+[followup_q]+s.questions[body.question_index+1:]
        turn["follow_up_question"]=public_question(followup_q)
    s.answers=s.answers+[saved]
    db.commit()
    next_index=body.question_index+1
    return {"answer":saved,"interviewer_response":turn["interviewer_response"],"follow_up":turn.get("follow_up_question"),"provider":turn["provider"],"next_index":next_index,"has_next":next_index<len(s.questions),"total":len(s.questions)}

@app.post("/api/interviews/{interview_id}/aptitude-submit")
def aptitude_submit(interview_id:int,body:AptitudeSubmit,user:User=Depends(current_user),db:Session=Depends(get_db)):
    s=db.query(Interview).filter(Interview.id==interview_id,Interview.user_id==user.id).first()
    if not s: raise HTTPException(404,"Interview not found.")
    if s.mode not in {"aptitude","mcq"}: raise HTTPException(409,"This is not an aptitude assessment.")
    if s.status!="in_progress": raise HTTPException(409,"This assessment is already submitted.")
    answers=[]
    for i,q in enumerate(s.questions):
        chosen=body.selections.get(q["id"],[])
        if any(not isinstance(option,int) or option<0 or option>=len(q["options"]) for option in chosen): raise HTTPException(422,"An answer choice is out of range.")
        selected=sorted(set(chosen)); correct=sorted(q["correct"])
        score=100 if selected==correct else (-25 if q.get("negative_marking") else 0)
        answers.append({"question_index":i,"question":public_question(q),"answer":selected,"result":{"score":score,"breakdown":{"correctness":max(0,score)},"penalty":25 if score<0 else 0,"feedback":q["explanation"]+(" Incorrect answer: 25 points deducted." if score<0 else ""),"correct_option":correct,"selected":selected}})
    s.answers=answers; s.status="completed"; s.finished_at=datetime.now(timezone.utc)
    raw={"correct":sum(1 for a in answers if a["result"]["score"]==100),"total":len(answers),"score":max(0,round(sum(a["result"]["score"] for a in answers)/max(1,len(answers)))),"negative_marking":any(q.get("negative_marking") for q in s.questions),"duration_seconds":body.duration_seconds}
    s.report=build_report(s,raw); db.commit()
    return s.report

def build_report(s: Interview, aptitude: dict | None = None):
    scores=[a["result"]["score"] for a in s.answers]
    overall=max(0,round(sum(scores)/len(scores))) if scores else None
    skill_data={}
    for a in s.answers:
        skill=a["question"].get("topic","General"); skill_data.setdefault(skill,[]).append(a["result"]["score"])
    skill_scores=[{"skill":k,"score":max(0,round(sum(v)/len(v)))} for k,v in skill_data.items()]
    communication=[a.get("result",{}).get("communication",{}) for a in s.answers]
    durations=[a.get("duration_seconds") for a in s.answers if a.get("duration_seconds") is not None]
    best=max(s.answers,key=lambda a:a["result"]["score"],default=None)
    weakest=min(s.answers,key=lambda a:a["result"]["score"],default=None)
    recommendations=[]
    if weakest: recommendations.append(f"Revisit {weakest['question'].get('topic','this topic')} and include the missing concepts: {', '.join(weakest['result'].get('concepts_missing',[])) or 'add a specific example'}.")
    if best and best["result"]["score"]>=75: recommendations.append(f"Build on your answer about {best['question'].get('topic','your strongest topic')} with deeper examples.")
    if not recommendations: recommendations.append("Complete more practice questions to receive targeted skill recommendations.")
    q_count=len(s.questions)
    speeds=[c["words_per_minute"] for c in communication if c.get("words_per_minute") is not None]
    return {
        "overall_score": overall,
        "score_label": "Practice performance only; not a hiring prediction.",
        "components": {"answer_quality": {"score": overall, "available": bool(scores), "weight": 1.0}},
        "correct_answers": sum(1 for value in scores if value >= 70),
        "total_questions": q_count,
        "answered": len(s.answers),
        "incomplete": len(s.answers) < q_count,
        "skill_scores": skill_scores,
        "strongest_skill": max(skill_scores, key=lambda x:x["score"], default=None),
        "weakest_skill": min(skill_scores, key=lambda x:x["score"], default=None),
        "questions_well_answered": [a["question"]["prompt"] for a in s.answers if a["result"]["score"] >= 70],
        "questions_to_improve": [a["question"]["prompt"] for a in s.answers if a["result"]["score"] < 70],
        "answer_details": [{
            "question": a["question"].get("prompt"), "topic": a["question"].get("topic"),
            "answer": a.get("answer"), "score": a["result"].get("score"),
            "breakdown": a["result"].get("breakdown"), "weights": a["result"].get("weights"),
            "concepts_covered": a["result"].get("concepts_covered", []),
            "concepts_missing": a["result"].get("concepts_missing", []),
            "feedback": a["result"].get("feedback"),
            "correct_option": a["result"].get("correct_option"),
            "selected": a["result"].get("selected"), "options": a["question"].get("options"),
        } for a in s.answers],
        "average_response_seconds": round(sum(durations)/len(durations),1) if durations else (round(aptitude["duration_seconds"]/len(s.answers),1) if aptitude and aptitude.get("duration_seconds") and s.answers else None),
        "communication": {
            "word_count": sum(c.get("word_count",0) for c in communication),
            "filler_count": sum(c.get("filler_count",0) for c in communication),
            "estimated_words_per_minute": round(sum(speeds)/len(speeds)) if speeds else None,
            "speech_speed_note": "Transcript and answer-duration estimate; not a voice quality judgment.",
        },
        "recommendations": recommendations,
        "next_session": "Practice the lowest-scoring topic with 3 focused questions.",
        "aptitude": aptitude,
        "score_method": "Per-answer rubric with configurable practice weights; unavailable components are omitted, not treated as zero.",
    }

@app.post("/api/interviews/{interview_id}/finish")
def finish_interview(interview_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    s=db.query(Interview).filter(Interview.id==interview_id,Interview.user_id==user.id).first()
    if not s: raise HTTPException(404,"Interview not found.")
    if s.status!="completed": s.status="completed"; s.finished_at=datetime.now(timezone.utc); s.report=build_report(s); db.commit()
    return s.report

@app.get("/api/interviews/{interview_id}/report")
def get_report(interview_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    s=db.query(Interview).filter(Interview.id==interview_id,Interview.user_id==user.id).first()
    if not s: raise HTTPException(404,"Interview not found.")
    if not s.report: raise HTTPException(409,"Finish the practice session to view its report.")
    return {"interview":session_summary(s),"report":s.report,"answers":s.answers}

@app.get("/api/interviews/history")
def history(user:User=Depends(current_user),db:Session=Depends(get_db)):
    sessions=db.query(Interview).filter(Interview.user_id==user.id).order_by(desc(Interview.created_at)).limit(100).all()
    return [session_summary(s) for s in sessions]

@app.get("/api/analytics/performance")
def analytics(user:User=Depends(current_user),db:Session=Depends(get_db)):
    sessions=db.query(Interview).filter(Interview.user_id==user.id,Interview.status=="completed").order_by(Interview.created_at).all()
    return [{"date":s.finished_at.isoformat() if s.finished_at else s.created_at.isoformat(),"score":s.report.get("overall_score"),"mode":s.mode} for s in sessions if s.report]

@app.post("/api/coach")
def learning_coach(body:CoachRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Build a personalized plan from completed answer reports belonging to this user."""
    sessions=db.query(Interview).filter(Interview.user_id==user.id,Interview.status=="completed").order_by(desc(Interview.created_at)).limit(100).all()
    return build_coach_plan(sessions,user_resume(db,user),allow_external_ai=body.allow_external_ai)

@app.get("/api/models/status")
def model_status():
    metadata_path=Path(__file__).resolve().parents[1]/"models"/"metadata.json"
    trained=metadata_path.exists()
    return {"answer_evaluator":{"type":"application rubric + lexical TF-IDF proxy","loaded":True,"pretrained":False,"app_trained":False},"completion_time_model":{"loaded":trained,"path":"backend/models/completion_time.joblib" if trained else None,"metadata":json.loads(metadata_path.read_text()) if trained else None,"purpose":"synthetic development completion-time estimate; never used for scoring"}}

class EstimateBody(BaseModel):
    question_count: int = Field(ge=1, le=30)
    difficulty: str
    mode: str
    resume_attached: bool = False

@app.post("/api/models/estimate")
def estimate_completion(body: EstimateBody):
    model_path=Path(__file__).resolve().parents[1]/"models"/"completion_time.joblib"
    if not model_path.exists(): raise HTTPException(503,"Train the separate development model first.")
    import joblib
    import pandas as pd
    pipeline=joblib.load(model_path)
    minutes=float(pipeline.predict(pd.DataFrame([{"question_count":body.question_count,"difficulty":body.difficulty,"mode":body.mode,"resume_attached":int(body.resume_attached)}]))[0])
    return {"estimate_minutes":round(minutes,1),"model_version":"completion-time-sim-v1","purpose":"Synthetic development estimate only; never used to score interview answers."}

@app.get("/api/question-bank")
def question_bank(): return {"topics":sorted(set(q["topic"] for q in BANK)),"modes":["voice","technical","behavioral","resume","aptitude","mcq","communication"],"difficulty":["beginner","intermediate","advanced"]}
