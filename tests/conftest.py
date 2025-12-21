"""Test configuration helpers."""

import sys
from pathlib import Path
import warnings
from cryptography.utils import CryptographyDeprecationWarning


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Silence the ARC4 cryptography deprecation emitted by pypdf while parsing PDFs
warnings.filterwarnings(
    "ignore",
    category=CryptographyDeprecationWarning,
    message=r".*ARC4 has been moved to cryptography\.hazmat\.decrepit\.ciphers\.algorithms\.ARC4.*",
)
