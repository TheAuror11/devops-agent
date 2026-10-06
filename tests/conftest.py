from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="devops-agent-test-")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATA_DIR", _tmp)
os.environ.setdefault("SEED_DEMO_DATA", "true")
os.environ.setdefault("QUEUE_BACKEND", "local")
os.environ.setdefault("STORE_BACKEND", "local")
os.environ.setdefault("BEDROCK_MODEL_ID", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("API_KEYS", "dev-local-key")
os.environ.setdefault("MAX_QUEUE_DEPTH", "0")
os.environ.setdefault("MAX_QUEUE_AGE_SECONDS", "0")
os.environ.setdefault("MAX_INVESTIGATIONS_PER_MINUTE", "10000")
