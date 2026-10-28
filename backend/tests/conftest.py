import os
import tempfile
from pathlib import Path
import pytest

ROOT = Path(tempfile.mkdtemp(prefix='resumeai-tests-'))
os.environ['DATABASE_URL'] = 'sqlite:///' + str(ROOT / 'test.db')
os.environ['DATABASE_BACKEND'] = 'sql'  # isolate regressions from the user's local Firestore .env
os.environ['STORAGE_DIR'] = str(ROOT / 'storage')
os.environ['GUEST_LIMIT_PER_HOUR'] = '1000'

from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        c.get('/api/config')
        yield c


@pytest.fixture
def resume_text():
    return '''Jordan Rivera
jordan@example.com
Professional Summary
Software engineer building accessible tools for people and reliable systems for teams.
Experience
Acme Systems | Software Engineer | 2021 - Present
Developed Python services to support customer workflows and automated reliable deployment checks.
Projects
Built a React dashboard using PostgreSQL to present accessible performance reports for internal teams.
Education
Computer Science coursework
Skills
Python, React, SQL, PostgreSQL, Git, Docker
'''
