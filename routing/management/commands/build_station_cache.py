"""``python manage.py build_station_cache`` -- warm the geocoded-station cache.

Run once after install (or whenever the price list changes) so the first real
API request doesn't pay the one-off geocoding/join cost.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from routing.services.fuel_data import _build_store


class Command(BaseCommand):
    help = "Geocode the fuel-price list against the offline gazetteer and cache it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Rebuild even if a cache file already exists.",
        )

    def handle(self, *args, **options):
        cache_path = Path(settings.STATION_CACHE)
        if options["force"] and cache_path.exists():
            cache_path.unlink()
            self.stdout.write(f"Removed existing cache {cache_path}")
        store = _build_store()
        self.stdout.write(self.style.SUCCESS(
            f"Cached {len(store.price)} geocoded truck stops at {cache_path}."
        ))
