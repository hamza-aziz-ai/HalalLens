"""Test configuration helpers."""

import sys
from pathlib import Path
import warnings

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Silence the ARC4 cryptography deprecation emitted by pypdf while parsing PDFs.
# `cryptography` arrives only as a transitive dependency of the PDF stack, so a
# missing install must not take the whole suite down at collection time.
try:
    from cryptography.utils import CryptographyDeprecationWarning
except ImportError:  # pragma: no cover - optional dependency
    pass
else:
    warnings.filterwarnings(
        "ignore",
        category=CryptographyDeprecationWarning,
        message=r".*ARC4 has been moved to cryptography\.hazmat\.decrepit\.ciphers\.algorithms\.ARC4.*",
    )


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Keep the module-level rate limiter from leaking state across tests."""

    try:
        from api.app import RATE_LIMITER
    except Exception:  # pragma: no cover - api package not importable here
        yield
        return
    RATE_LIMITER.reset()
    yield
    RATE_LIMITER.reset()
