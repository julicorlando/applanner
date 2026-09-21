from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DJANGO_DEBUG=(bool, False), SECURE_SSL_REDIRECT=(bool, True), EMAIL_USE_TLS=(bool, True))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")\nFIELD_ENCRYPTION_KEY = env("DJANGO_FIELD_ENCRYPTION_KEY")\nTRUSTED_DEVICE_DAYS = env.int("TRUSTED_DEVICE_DAYS", default=30)
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost","127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin","django.contrib.auth","django.contrib.contenttypes",
    "django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles",
    "rest_framework","django_celery_beat","core","tenants","accounts","scheduling","billing","finance",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF="applanner.urls"
WSGI_APPLICATION="applanner.wsgi.application"
ASGI_APPLICATION="applanner.asgi.application"

TEMPLATES=[{
    "BACKEND":"django.template.backends.django.DjangoTemplates",
    "DIRS":[BASE_DIR/"templates"],"APP_DIRS":True,
    "OPTIONS":{"context_processors":[
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
DATABASES={"default":env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"]=60
CACHES={"default":{"BACKEND":"django_redis.cache.RedisCache","LOCATION":env("REDIS_URL",default="redis://redis:6379/0"),"OPTIONS":{"CLIENT_CLASS":"django_redis.client.DefaultClient"}}}

AUTH_USER_MODEL="accounts.User"
AUTH_PASSWORD_VALIDATORS=[
    {"NAME":"django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator","OPTIONS":{"min_length":12}},
    {"NAME":"django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME":"django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS=[
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "accounts.hashers.PHPBcryptPasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
LANGUAGE_CODE="pt-br"
LANGUAGES=[("pt-br","Português (Brasil)"),("pt","Português"),("en","English"),("es","Español")]
TIME_ZONE=env("TIME_ZONE",default="America/Recife")
USE_I18N=True
USE_TZ=True
STATIC_URL="/static/"
STATIC_ROOT=BASE_DIR/"staticfiles"
MEDIA_URL="/media/"
MEDIA_ROOT=BASE_DIR/"media"
STORAGES={
    "default":{"BACKEND":"django.core.files.storage.FileSystemStorage"},
    "staticfiles":{"BACKEND":"whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD="django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE="Lax"
CSRF_COOKIE_SAMESITE="Lax"
SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")
SECURE_SSL_REDIRECT=env.bool("SECURE_SSL_REDIRECT",default=not DEBUG)
SESSION_COOKIE_SECURE=not DEBUG
CSRF_COOKIE_SECURE=not DEBUG
SECURE_HSTS_SECONDS=31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS=not DEBUG
SECURE_HSTS_PRELOAD=not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF=True
X_FRAME_OPTIONS="DENY"
SECURE_REFERRER_POLICY="same-origin"

REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES":["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES":["rest_framework.throttling.AnonRateThrottle","rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES":{"anon":"60/min","user":"600/min"},
}
CELERY_BROKER_URL=env("CELERY_BROKER_URL",default="redis://redis:6379/1")
CELERY_RESULT_BACKEND=env("CELERY_RESULT_BACKEND",default="redis://redis:6379/2")
CELERY_TASK_ACKS_LATE=True
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_BEAT_SCHEDULER="django_celery_beat.schedulers:DatabaseScheduler"

EMAIL_BACKEND=env("EMAIL_BACKEND",default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST=env("EMAIL_HOST",default="")
EMAIL_PORT=env.int("EMAIL_PORT",default=587)
EMAIL_HOST_USER=env("EMAIL_HOST_USER",default="")
EMAIL_HOST_PASSWORD=env("EMAIL_HOST_PASSWORD",default="")
EMAIL_USE_TLS=env.bool("EMAIL_USE_TLS",default=True)
DEFAULT_FROM_EMAIL=env("DEFAULT_FROM_EMAIL",default="contato@applanner.com.br")

SENTRY_DSN=env("SENTRY_DSN",default="")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=SENTRY_DSN,send_default_pii=False,traces_sample_rate=0.05)
