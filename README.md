# AI Interview Pro

A local-first interview practice platform. The React/Vite client talks to a FastAPI service backed by SQLite (or PostgreSQL when `DATABASE_URL` is configured).

## Quick start

1. Install Python 3.11+ and Node.js 20.19+.
2. Copy `.env.example` to `.env` and adjust values if needed.
3. In one terminal, install and start the API:

   ```powershell
   cd backend
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn app.main:app --reload
   ```

4. In another terminal, install and start the web app:

   ```powershell
   npm install
   npm run dev
   ```

Open the Vite URL printed in the terminal (usually `http://localhost:5173`). API docs are at `http://localhost:8000/docs`.

## Current capabilities

- Register and sign in with hashed passwords and bearer tokens; development tokens are local JWTs.
- Dashboard with practice stats, history, skill breakdown, and recommendations.
- Personalized learning coach at `/api/coach`, grounded in the signed-in user's completed scored answers, recurring missed concepts, saved feedback, role, and extracted resume skills. Without sufficient scored answers it offers a short diagnostic instead of guessing at weak topics. A configured OpenAI-compatible provider can enhance the study plan only after the user explicitly opts in; answer scoring remains local and unchanged.
- PDF/DOCX/TXT resume upload, text extraction, heuristic skill/project extraction, and editable extracted skills.
- Resume-aware question selection with topic and difficulty controls.
- Typed interview answers, browser speech recognition (when available), browser text-to-speech, optional job-description alignment, and explainable rubric scoring.
- Dedicated conversational voice interview mode: interviewer speech, editable browser transcription, per-turn rubric evaluation, remembered session answers, adaptive clarification/follow-up prompts, and saved answer-level report details.
- Timed aptitude/MCQ session with answer validation and review.
- History and per-session reports persisted in SQLite.
- A separate scikit-learn pipeline that predicts **synthetic development session completion time**. Its outputs are experimental and never used as an interview score.

## Evaluation and model boundaries

Answer evaluation combines a concept checklist, answer structure, and scikit-learn TF-IDF cosine similarity against the question and reference answer. TF-IDF is a local lexical baseline, not a Sentence Transformer and not proof of technical correctness. Scores are practice feedback, not hiring predictions. The default rubric weights are shown in each evaluation response. Communication metrics are transcript-derived estimates (WPM, filler counts, repetition); browser recognition does not provide reliable word-level timing, so pause measurements are unavailable. Accent, emotion, confidence, honesty, personality, and employability are not inferred.

The training experiment uses a reproducibly generated synthetic dataset with an explicit target (`completion_minutes`) and known feature schema. Reported metrics describe only this synthetic development task. No model is shipped as an objectively accurate interview evaluator.

Speech uses the browser's Web Speech API when the browser offers it. It may send audio to the browser vendor's speech service; this application does not retain raw audio. If recognition is missing, typed practice stays available. Question reading and interviewer responses use browser speech synthesis. The conversational follow-up policy works offline and uses the saved session transcript plus the rubric result. The learning coach builds a local evidence-based plan by default. If an OpenAI-compatible provider is configured, a user can explicitly opt in to send a limited set of answer excerpts, scores, feedback, topic gaps, role, and resume skill names to enhance the plan. Resume document contents and answer scoring are never sent or delegated by this coach flow.

## Configuration

See `.env.example`. SQLite is the default, and its relative path is anchored to the backend folder so launching the API from another working directory still uses the same database. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL to use PostgreSQL. Set a long `JWT_SECRET` for any shared deployment. `VITE_API_URL` configures the browser API base. Keep API secrets on the backend. Upload limit defaults to 8 MB. The original resume file, extracted text, and skills are stored in the database and the original file can be downloaded from the Resume workspace. Do not deploy this development setup with sensitive resumes without adding a retention and access policy.

## ML training experiment

```powershell
cd backend
python -m app.ml.train
```

The script prints train/test MAE and R² and writes the fitted pipeline plus version metadata into `backend/models/`. The data generator and schema are in `app/ml/train.py`. This model is not used for interview grading.

## Tests and known limits

Backend tests: `cd backend; pytest`. Frontend checks: `npm test` and `npm run build`. PDF/DOCX parsing depends on PyMuPDF/python-docx. The first Alembic migration is in `backend/migrations`. Semantic comparison is a TF-IDF baseline; no pretrained transformer weights are downloaded. Resume extraction and local follow-up generation use transparent heuristics. Hosted interviewer generation is optional and requires credentials and explicit per-session consent. Speech recognition quality and availability depend on the browser. Authentication is suitable for local practice, but production requires HTTPS, a strong secret, distributed rate limiting, email verification, refresh-token/session revocation, and hardened upload retention. Registration and login use a small per-process IP rate limit for local development.
