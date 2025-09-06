# FPL/FPL/celery.py
import os
from celery import Celery

# set default Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FPL.settings")

app = Celery("FPL")

# load settings from Django settings.py, namespace CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# auto-discover tasks.py from all apps
app.autodiscover_tasks()
