def register(client,email="candidate@example.com"):
    r=client.post("/api/auth/register",json={"email":email,"password":"secure-pass-123","name":"Taylor Candidate"})
    assert r.status_code==200
    client.headers.update({"Authorization":f"Bearer {r.json()['access_token']}"})
    return r.json()

def test_register_login_and_private_dashboard(client):
    account=register(client)
    assert account["user"]["name"]=="Taylor Candidate"
    assert client.get("/api/dashboard").json()["stats"]["completed"]==0
    assert client.post("/api/auth/login",json={"username":"candidate@example.com","password":"wrong-password"}).status_code==401

def test_practice_history_route_is_not_captured_by_interview_id_route(client):
    register(client)
    started=client.post("/api/interviews/start",json={"mode":"technical","difficulty":"beginner","count":3}).json()

    history=client.get("/api/interviews/history")
    assert history.status_code==200
    assert len(history.json())==1
    assert history.json()[0]["id"]==started["id"]
    assert history.json()[0]["status"]=="in_progress"

    finished=client.post(f"/api/interviews/{started['id']}/finish")
    assert finished.status_code==200
    completed=client.get("/api/interviews/history")
    assert completed.status_code==200
    assert completed.json()[0]["status"]=="completed"

def test_learning_coach_uses_only_authenticated_completed_answer_evidence(client):
    account=register(client)
    from app.models import Interview
    from conftest import TestSession
    db=TestSession()
    try:
        def answer(topic, score, missing):
            return {"question":{"topic":topic,"prompt":f"Explain {topic}."},"answer":f"An answer about {topic}.","result":{"score":score,"concepts_missing":missing,"feedback":"Add a concrete example."}}
        db.add(Interview(user_id=account["user"]["id"],mode="technical",role="Data Engineer",status="completed",questions=[],
            answers=[answer("Python",35,["inheritance"]),answer("Python",45,["inheritance","polymorphism"]),answer("SQL",80,[]),answer("SQL",80,[])],
            report={"overall_score":60}))
        db.add(Interview(user_id=account["user"]["id"],mode="technical",role="Data Engineer",status="in_progress",questions=[],
            answers=[answer("React",0,["hooks"])],report=None))
        db.commit()
    finally:
        db.close()

    response=client.post("/api/coach",json={"allow_external_ai":False})
    assert response.status_code==200
    coach=response.json()
    assert coach["has_baseline"] is True
    assert coach["sessions_analyzed"]==1
    assert coach["answers_analyzed"]==4
    assert coach["focus_topic"]=="Python"
    assert coach["weak_topics"][0]["measured_score"]==40
    assert coach["weak_topics"][0]["priority"]=="high"
    assert "inheritance" in coach["weak_topics"][0]["common_gaps"]
    assert len(coach["plan"])>=1

def test_learning_coach_diagnostic_does_not_invent_weakness_without_history(client):
    register(client)
    response=client.post("/api/coach",json={"allow_external_ai":False})
    assert response.status_code==200
    coach=response.json()
    assert coach["has_baseline"] is False
    assert coach["weak_topics"]==[]
    assert coach["focus_topic"] is None
    assert "diagnostic" in coach["headline"].lower()

def test_coach_only_sends_answer_evidence_to_configured_ai_after_explicit_opt_in(client,monkeypatch):
    account=register(client)
    from app.models import Interview
    from app import coach as coach_module
    from conftest import TestSession
    db=TestSession()
    try:
        answers=[{"question":{"topic":"Python","prompt":"Explain Python inheritance."},"answer":"My saved Python answer.","result":{"score":40,"concepts_missing":["method resolution order"],"feedback":"Explain method lookup."}} for _ in range(3)]
        db.add(Interview(user_id=account["user"]["id"],mode="technical",role="Software Engineer",status="completed",questions=[],answers=answers,report={"overall_score":40}))
        db.commit()
    finally:
        db.close()

    sent=[]
    monkeypatch.setattr(coach_module.settings,"openai_api_key","test-key")
    def fake_provider(system_prompt,user_data,temperature):
        sent.append(user_data)
        return {"objective":"Explain Python inheritance clearly.","steps":[{"title":"Practice inheritance","minutes":15,"action":"Review the saved gap.","practice":"Answer a question.","success_criteria":"Score 70/100.","after":"Review the feedback."}]}
    monkeypatch.setattr(coach_module,"hosted_json_completion",fake_provider)

    local=client.post("/api/coach",json={"allow_external_ai":False}).json()
    assert local["coach_mode"]=="evidence_based_local"
    assert sent==[]

    enhanced=client.post("/api/coach",json={"allow_external_ai":True}).json()
    assert enhanced["coach_mode"]=="external_ai"
    assert enhanced["plan"][0]["title"]=="Practice inheritance"
    assert sent[0]["focus_topic"]=="Python"
    assert sent[0]["evidence"][0]["question"]=="Explain Python inheritance."

def test_dashboard_kpis_handle_null_aptitude_and_aggregate_completed_sessions(client):
    account=register(client)
    from app.models import Interview
    from conftest import TestSession
    db=TestSession()
    try:
        db.add_all([
            Interview(user_id=account["user"]["id"],mode="technical",status="completed",questions=[],
                answers=[{"duration_seconds":60}],report={"overall_score":80,"aptitude":None,"skill_scores":[{"skill":"Python","score":80},{"skill":" SQL ","score":60}]}),
            Interview(user_id=account["user"]["id"],mode="aptitude",status="completed",questions=[],
                answers=[{"duration_seconds":None}],report={"overall_score":40,"aptitude":{"duration_seconds":90},"skill_scores":[{"skill":"python","score":100}]}),
            Interview(user_id=account["user"]["id"],mode="technical",status="in_progress",questions=[],answers=[],
                report={"overall_score":100,"skill_scores":[{"skill":"Rust","score":100}]}),
        ])
        db.commit()
    finally:
        db.close()

    response=client.get("/api/dashboard")
    assert response.status_code==200
    stats=response.json()["stats"]
    assert stats=={"completed":2,"average_score":60,"minutes_practiced":3}
    assert {skill["skill"].strip().casefold() for skill in response.json()["skills"]}=={"python","sql"}

def test_interview_answer_and_report_are_persisted(client):
    register(client)
    start=client.post("/api/interviews/start",json={"mode":"technical","topic":"SQL","difficulty":"beginner","count":3}).json()
    assert start["questions"]
    q=start["questions"][0]
    answer=client.post(f"/api/interviews/{start['id']}/submit-answer",json={"question_index":0,"answer":"An INNER JOIN returns matching rows. A LEFT JOIN preserves every left table row and gives NULL for missing right matches.","duration_seconds":30})
    assert answer.status_code==200
    report=client.post(f"/api/interviews/{start['id']}/finish").json()
    assert report["answered"]==1 and report["incomplete"] is (1 < start["total"])
    assert report["answer_details"][0]["breakdown"]["correctness"]>0
    assert client.get(f"/api/interviews/{start['id']}/report").json()["report"]["overall_score"]==report["overall_score"]

def test_conversational_voice_turn_can_insert_follow_up_and_finish_report(client):
    register(client)
    started=client.post("/api/interviews/start",json={"mode":"voice","difficulty":"beginner","count":3}).json()
    assert started["mode"]=="voice"
    first=client.post(f"/api/interviews/{started['id']}/conversation-turn",json={"question_index":0,"answer":"Rows.","duration_seconds":2})
    assert first.status_code==200
    turn=first.json()
    assert turn["interviewer_response"] and turn["provider"]=="local_policy"
    assert turn["follow_up"] and turn["follow_up"]["is_follow_up"]
    follow=client.post(f"/api/interviews/{started['id']}/conversation-turn",json={"question_index":1,"answer":"I would include a concrete example and explain the result of my approach.","duration_seconds":12})
    assert follow.status_code==200
    assert follow.json()["next_index"]==2
    report=client.post(f"/api/interviews/{started['id']}/finish").json()
    assert report["answered"]==2 and report["total_questions"]==4
    assert report["answer_details"][1]["question"].startswith("Could you add")

def test_ownership_is_enforced(client):
    register(client)
    start=client.post("/api/interviews/start",json={"mode":"technical"}).json()
    other=client.post("/api/auth/register",json={"email":"other@example.com","password":"secure-pass-123","name":"Other"}).json()
    client.headers.update({"Authorization":f"Bearer {other['access_token']}"})
    response=client.get(f"/api/interviews/{start['id']}/report")
    assert response.status_code==404

def test_empty_answer_and_speech_metrics_are_explicit():
    from app.evaluation import evaluate, communication_metrics
    question={"prompt":"Explain SQL indexes","concepts":["lookup","storage"]}
    assert evaluate(question,"")["score"]==0
    metrics=communication_metrics("Um, an index speeds lookup. It uses storage.")
    assert metrics["filler_count"]==1 and metrics["duration_seconds"] is None

def test_resume_upload_is_private_and_questions_use_extracted_skills(client):
    register(client)
    uploaded=client.post("/api/resumes/upload",files={"file":("resume.txt",b"Skills: Python, SQL\nProjects\nBuilt a Python sales forecasting service for a retail team.","text/plain")})
    assert uploaded.status_code==200
    assert "Python" in uploaded.json()["skills"] and "SQL" in uploaded.json()["skills"]
    started=client.post("/api/interviews/start",json={"mode":"resume","resume_id":uploaded.json()["id"],"difficulty":"beginner","count":3}).json()
    assert any("Python" in q["prompt"] for q in started["questions"])

def test_original_resume_is_saved_and_can_be_downloaded(client):
    register(client)
    content=b"Skills: Python, SQL\nProjects\nBuilt a reporting tool."
    uploaded=client.post("/api/resumes/upload",files={"file":("resume.txt",content,"text/plain")})
    assert uploaded.status_code==200
    assert uploaded.json()["file_saved"] is True
    assert uploaded.json()["file_size_bytes"]==len(content)
    downloaded=client.get(f"/api/resumes/{uploaded.json()['id']}/download")
    assert downloaded.status_code==200
    assert downloaded.content==content
    assert "resume.txt" in downloaded.headers["content-disposition"]

def test_job_description_adds_a_role_alignment_question(client):
    register(client)
    started=client.post("/api/interviews/start",json={"mode":"technical","job_description":"Python and SQL required","role":"Data Analyst"}).json()
    assert started["questions"][0]["topic"]=="Role alignment"

def test_negative_marking_is_optional_and_explained(client):
    from app.questions import APTITUDE
    register(client)
    started=client.post("/api/interviews/start",json={"mode":"aptitude","difficulty":"beginner","count":3,"negative_marking":True}).json()
    selections={}
    for q in started["questions"]:
        source=next(x for x in APTITUDE if x["id"]==q["id"])
        selections[q["id"]]=[(source["correct"][0]+1)%len(source["options"])]
    report=client.post(f"/api/interviews/{started['id']}/aptitude-submit",json={"selections":selections}).json()
    assert report["aptitude"]["negative_marking"] is True
    assert all("25 points deducted" in a["feedback"] for a in report["answer_details"])
