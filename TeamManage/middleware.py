from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from .services import finalize_expired_bids

class FinalizeBidsMiddleware(MiddlewareMixin):
    CHECK_INTERVAL = 300  # seconds (5 minutes)

    def process_request(self, request):
        """
        Runs before every view, but only triggers finalize_expired_bids()
        if the last check was more than CHECK_INTERVAL seconds ago.
        """
        try:
            last_check = cache.get("last_bid_check_time")
            now = timezone.now()

            if not last_check or (now - last_check) > timedelta(seconds=self.CHECK_INTERVAL):
                finalize_expired_bids()
                cache.set("last_bid_check_time", now, timeout=None)

        except Exception as e:
            # Avoid breaking the request if something goes wrong
            print(f"[BID CHECK ERROR] {e}")

        return None

