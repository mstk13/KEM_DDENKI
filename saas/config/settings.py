"""
Django settings for kensetsu-saas project.
"""

import mimetypes
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Windows / slim イメージには .webmanifest の登録がなく、そのままだと
# application/octet-stream で配信されてブラウザが PWA として認識しない。
mimetypes.add_type("application/manifest+json", ".webmanifest")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

_csrf_origins = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = _csrf_origins.split(",")
else:
    CSRF_TRUSTED_ORIGINS = [f"http://{h}:8000" for h in ALLOWED_HOSTS if h and h != "*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "simple_history",
    # Local apps — order matters
    "apps.core",
    "apps.tenants",
    "apps.accounts",
    "apps.masters",
    "apps.workers",
    "apps.sites",
    "apps.materials",
    "apps.reports",
    "apps.costs",
    "apps.devkanri",
    "apps.schedules",
    "apps.bids",
    "apps.notifications",
    "apps.permissions",
    "apps.sales",
    "apps.evaluation",
    "apps.attendance",
    "apps.ai",
    "apps.estimation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.NoCacheMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.TenantMiddleware",
    "apps.core.middleware.AppPermissionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.branding",
                "apps.core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "kensetsu_saas"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# Use SQLite for testing (CI / pytest)
if os.environ.get("USE_SQLITE", "").lower() in ("true", "1", "yes"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# WhiteNoise は独自の MimeTypes インスタンスを持つため、上の mimetypes.add_type だけでは
# 反映されない。実際の配信はこちらの設定が使われる。
WHITENOISE_MIMETYPES = {
    ".webmanifest": "application/manifest+json",
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SIMPLE_HISTORY_REVERT_DISABLED = True

# ---- Branding (SaaS外販時にここだけ変更すればOK) ----
APP_NAME = os.environ.get("APP_NAME", "KEC")
APP_NAME_FULL = os.environ.get("APP_NAME_FULL", "KEC 業務管理システム")
APP_SUBTITLE = os.environ.get("APP_SUBTITLE", "業務管理プラットフォーム")
APP_THEME_COLOR = os.environ.get("APP_THEME_COLOR", "#1a2744")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# 社長用ログインPIN（環境変数で上書き可能）
PRESIDENT_PIN = os.environ.get("PRESIDENT_PIN", "1234")

# ---- AI API 使用量制限 ----
# 月間上限（円）。超過するとAI機能を自動停止する。
AI_MONTHLY_BUDGET_JPY = int(os.environ.get("AI_MONTHLY_BUDGET_JPY", "4000"))
# USD→JPYレート（概算。正確なレートは不要）
AI_USD_TO_JPY_RATE = int(os.environ.get("AI_USD_TO_JPY_RATE", "152"))

# ---- ローカル推論 (Ollama) ----
# ADR-0010「AI推論の3層分割」の層A・層B。
# Ollama はホストの Windows 側で稼働するため、コンテナからは
# host.docker.internal で到達する。到達できない場合は各サービスが
# 黙って Claude API へフォールバックするので、未設定でも動作する。
OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
)
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
OLLAMA_EMBED_TIMEOUT = int(os.environ.get("OLLAMA_EMBED_TIMEOUT", "60"))
OLLAMA_EMBED_ENABLED = os.environ.get(
    "OLLAMA_EMBED_ENABLED", "True"
).lower() in ("true", "1", "yes")
# モデルをVRAMに常駐させる時間。ホスト側のシステム環境変数に
# OLLAMA_KEEP_ALIVE=0 が入っており、無指定だとリクエストのたびに
# アンロードされて毎回の再ロードが応答時間に乗る（実測 3.3秒 → 0.27秒）。
# リクエスト単位の keep_alive はサーバ側の環境変数より優先されるため、
# ホストの設定を変更せずにこちらで上書きする。
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "5m")

# 層B（生成モデル）。層Aの埋め込みと違い、既定は無効。
# 精度をタスクごとに実測して確認してから有効化する運用にする
# （労務単価表では決定論的パーサ 1.000 に対しローカル 0.64 だった）。
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "qwen3:8b")
OLLAMA_CHAT_TIMEOUT = int(os.environ.get("OLLAMA_CHAT_TIMEOUT", "300"))
OLLAMA_CHAT_ENABLED = os.environ.get(
    "OLLAMA_CHAT_ENABLED", "False"
).lower() in ("true", "1", "yes")
# 8B + KVキャッシュが GPU に収まる上限。伸ばすと CPU に溢れて速度が落ちる。
OLLAMA_CHAT_NUM_CTX = int(os.environ.get("OLLAMA_CHAT_NUM_CTX", "8192"))

# ---- Email (SMTP) ----
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False").lower() in ("true", "1", "yes")
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@kem-ddenki.com")
EMAIL_SUBJECT_PREFIX = "[KEC通知] "
