from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from .services import finalize_expired_bids

class FinalizeBidsMiddleware(MiddlewareMixin):
    def process_request(self, request):
        finalize_expired_bids()
        return None

