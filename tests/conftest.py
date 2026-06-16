import sys
from pathlib import Path

# Make the repo root importable so `import sparky` works without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
