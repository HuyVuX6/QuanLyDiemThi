# -*- coding: utf-8 -*-
import importlib
from . import school
from . import exam
from . import ai_analysis

try:
    importlib.reload(school)
    importlib.reload(exam)
    importlib.reload(ai_analysis)
except Exception:
    pass
    pass