"""Reproducible development-only regression experiment on labeled synthetic data."""
import json
from pathlib import Path
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
import joblib

SEED = 23
FEATURES = ["question_count", "difficulty", "mode", "resume_attached"]
TARGET = "completion_minutes"

def run():
    rng = np.random.default_rng(SEED)
    n = 800
    X = {
      "question_count": rng.integers(3, 13, n),
      "difficulty": rng.choice(["beginner","intermediate","advanced"], n),
      "mode": rng.choice(["technical","behavioral","aptitude","resume"], n),
      "resume_attached": rng.choice([0,1], n),
    }
    # Explicit simulated target formula; labels are not interview-quality labels.
    y = (X["question_count"] * 2.6 + np.select([X["difficulty"]=="beginner",X["difficulty"]=="advanced"],[0,5],default=2) + np.select([X["mode"]=="aptitude",X["mode"]=="resume"],[1,-1],default=0) - X["resume_attached"]*.7 + rng.normal(0,2.5,n))
    import pandas as pd
    frame = pd.DataFrame(X)
    numeric = ["question_count","resume_attached"]
    categorical = ["difficulty","mode"]
    preprocess = ColumnTransformer([("categorical",OneHotEncoder(handle_unknown="ignore"),categorical),("numeric","passthrough",numeric)])
    pipeline = Pipeline([("preprocess",preprocess),("regressor",RandomForestRegressor(n_estimators=180,min_samples_leaf=2,random_state=SEED))])
    X_train, X_test, y_train, y_test = train_test_split(frame,y,test_size=.2,random_state=SEED)
    pipeline.fit(X_train,y_train)
    predictions = pipeline.predict(X_test)
    metrics = {"target":TARGET,"features":FEATURES,"seed":SEED,"train_rows":len(X_train),"test_rows":len(X_test),"mae_minutes":round(float(mean_absolute_error(y_test,predictions)),3),"r2":round(float(r2_score(y_test,predictions)),3),"data":"synthetic development only; not an interview quality dataset","model_version":"completion-time-sim-v1"}
    out = Path(__file__).resolve().parents[2] / "models"
    out.mkdir(exist_ok=True)
    joblib.dump(pipeline,out/"completion_time.joblib")
    (out/"metadata.json").write_text(json.dumps(metrics,indent=2))
    print(json.dumps(metrics,indent=2))
    return metrics

if __name__ == "__main__": run()
