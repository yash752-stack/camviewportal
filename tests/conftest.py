import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
# every test run gets its own data folder, so nothing touches the real database
os.environ.setdefault("CAMVIEW_DATA_DIR", tempfile.mkdtemp(prefix="camview-test-"))
