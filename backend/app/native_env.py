"""Forward the deployed Python import path to bounded parser subprocesses.

Vercel injects installed packages into sys.path; invoking sys.executable does not
otherwise inherit that path. Never forward request content as command-line code.
"""
import os
import sys


def worker_env(scratch):
    # Native document codecs do not need database, AI, email or Blob credentials.
    private=lambda key:any(term in key.upper() for term in ('TOKEN','SECRET','PASSWORD','CREDENTIAL','API_KEY')) or key=='DATABASE_URL'
    return {**{key:value for key,value in os.environ.items() if not private(key)},'OMP_THREAD_LIMIT':'1','TMPDIR':str(scratch),
            'PYTHONPATH':os.pathsep.join(dict.fromkeys(str(p) for p in sys.path if p))}
