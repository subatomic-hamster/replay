import sys
from pathlib import Path

# run from render/ without installing: `cd render && python -m pytest -q`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
