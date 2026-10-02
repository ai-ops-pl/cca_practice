from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only-not-for-production-ccar-mock-exam"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "exam",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Exam configuration (mirrors the Claude Certified Architect - Foundations
# exam guide, v1.0, July 2026)
# ---------------------------------------------------------------------------
EXAM = {
    "CODE": "CCAR-F",
    "NAME": "Claude Certified Architect - Foundations (Mock)",
    "ITEM_COUNT": 60,
    "DURATION_MINUTES": 120,
    "SCALED_MIN": 100,
    "SCALED_MAX": 1000,
    "CUT_SCORE": 720,
    # Raw proportion correct that maps exactly to the 720 cut score.
    "CUT_RAW": 0.70,
    "DOMAINS": {
        "D1": {"name": "Agentic Architecture & Orchestration", "weight": 27},
        "D2": {"name": "Tool Design & MCP Integration", "weight": 18},
        "D3": {"name": "Claude Code Configuration & Workflows", "weight": 20},
        "D4": {"name": "Prompt Engineering & Structured Output", "weight": 20},
        "D5": {"name": "Context Management & Reliability", "weight": 15},
    },
}
