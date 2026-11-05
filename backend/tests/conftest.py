import os
import tempfile

# Point the app at a throwaway database before any app module creates its engine.
_DB_DIR = tempfile.mkdtemp(prefix="nestleap-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_DIR}/test.db"
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("ADMIN_KEY", "test-admin-key")
