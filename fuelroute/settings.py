"""Django settings for the fuelroute project (Django 6.0)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "fuelroute.urls"
WSGI_APPLICATION = "fuelroute.wsgi.application"
ASGI_APPLICATION = "fuelroute.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

# No relational models are used; the price list is a flat file. A throwaway
# SQLite file keeps Django happy without provisioning a real database.
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuelroute-cache",
    }
}

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    # This API is intentionally open; no auth/user model needed.
    "UNAUTHENTICATED_USER": None,
}

# --------------------------------------------------------------------------- #
# Domain configuration -- every knob is overridable via environment variable.
# --------------------------------------------------------------------------- #
DATA_DIR = Path(os.environ.get("FUELROUTE_DATA_DIR", BASE_DIR / "data"))
FUEL_PRICES_CSV = os.environ.get("FUEL_PRICES_CSV", str(DATA_DIR / "fuel-prices.csv"))
US_CITIES_CSV = os.environ.get("US_CITIES_CSV", str(DATA_DIR / "us_cities.csv"))
STATION_CACHE = os.environ.get("STATION_CACHE", str(DATA_DIR / "stations_cache.npz"))

# Vehicle / problem parameters
VEHICLE_RANGE_MILES = float(os.environ.get("VEHICLE_RANGE_MILES", "500"))
VEHICLE_MPG = float(os.environ.get("VEHICLE_MPG", "10"))

# How far off-route a truck stop may sit and still count as "along the route".
# Generous by default because stops are geocoded to their town centre (the feed
# has no exact coordinates), so the centroid can sit a little off the highway.
FUEL_CORRIDOR_MILES = float(os.environ.get("FUEL_CORRIDOR_MILES", "25"))
# Spacing used to thin the route polyline before matching (accuracy vs. speed).
ROUTE_SAMPLE_MILES = float(os.environ.get("ROUTE_SAMPLE_MILES", "2"))

# Routing provider (OSRM-compatible). Override to use a self-hosted instance.
OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "20"))

# Optional address geocoding fallback (off by default to minimise calls).
NOMINATIM_FALLBACK = _env_bool("NOMINATIM_FALLBACK", False)
NOMINATIM_USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "fuelroute-demo/1.0")

# Cache lifetimes (seconds)
ROUTE_CACHE_TTL = int(os.environ.get("ROUTE_CACHE_TTL", "86400"))
GEOCODE_CACHE_TTL = int(os.environ.get("GEOCODE_CACHE_TTL", "604800"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
