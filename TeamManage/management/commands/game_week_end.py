from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from TeamManage.models import SeasonConfig, TransferHistory  # ✅ adjust app name

class Command(BaseCommand):
    help = "End loans for players whose loan_gameweek matches the current active gameweek."

    def handle(self, *args, **options):
        active_season = SeasonConfig.get_active_season()
        if not active_season:
            self.stdout.write(self.style.ERROR("❌ No active season found."))
            return

        current_gw = active_season.current_gameweek
        self.stdout.write(f"🔍 Checking for loans ending at Gameweek {current_gw}...")

        loans_to_end = (
            TransferHistory.objects
            .filter(is_loan=True, is_loan_end=False, loan_gameweek=current_gw)
            .select_related("player", "from_team", "to_team")
        )

        if not loans_to_end.exists():
            self.stdout.write(self.style.WARNING("No loans scheduled to end this gameweek."))
            return

        ended_count = 0

        for history in loans_to_end:
            player = history.player
            old_team = history.from_team
            current_team = history.to_team

            if not old_team:
                self.stdout.write(
                    self.style.WARNING(f"⚠ {player.full_name} skipped (no original team).")
                )
                continue

            with transaction.atomic():
                # restore player states
                player.is_academy_player = player.was_academy_player
                player.was_academy_player = False
                player.is_locked = player.was_locked
                player.was_locked = False
                player.team = old_team
                player.is_loan = False
                player.loan_from_team = None
                player.save()

                # mark history
                history.is_loan_end = True
                history.save()

                # record the return transfer
                TransferHistory.objects.create(
                    season=active_season,
                    player=player,
                    from_team=current_team,
                    to_team=old_team,
                    amount=Decimal("0"),
                    is_loan_end=True,
                )

                ended_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"✅ Ended {ended_count} loan(s) for Gameweek {current_gw}.")
        )
