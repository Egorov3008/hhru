"""Код hh-agent лежит в tools/hh-agent — добавляем его в sys.path для тестов."""

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
