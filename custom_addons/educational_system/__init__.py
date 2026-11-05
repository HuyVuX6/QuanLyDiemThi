# -*- coding: utf-8 -*-
import importlib
from . import utils
from . import models
from . import controllers

try:
    if hasattr(utils, 'omr_engine'):
        importlib.reload(utils.omr_engine)
    if hasattr(models, 'school'):
        importlib.reload(models.school)
    if hasattr(models, 'exam'):
        importlib.reload(models.exam)
    if hasattr(models, 'ai_analysis'):
        importlib.reload(models.ai_analysis)
except Exception:
    pass