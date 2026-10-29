import os
os.environ["DATABASE_URL"]="sqlite:///./test_app.db"
os.environ["JWT_SECRET"]="test-secret-for-test-only"
import pytest
import asyncio
if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    # The sandbox disables the socketpair used by Windows' Proactor loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from fastapi.testclient import TestClient
from app.main import app, _auth_attempts
from app.database import Base, engine, get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_ENGINE=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=__import__('sqlalchemy').pool.StaticPool)
TestSession=sessionmaker(bind=TEST_ENGINE,autoflush=False,expire_on_commit=False)

@pytest.fixture
def client():
    _auth_attempts.clear()
    Base.metadata.create_all(TEST_ENGINE)
    def override_db():
        db=TestSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    with TestClient(app) as c: yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(TEST_ENGINE)
