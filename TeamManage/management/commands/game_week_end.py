from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from TeamManage.signals import player_loan_ended
from TeamManage.models import SeasonConfig, TransferHistory, Player

import requests


class Command(BaseCommand):
    help = "End gameweek by updating player points and processing loan returns."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("🏁 Starting Gameweek End Process..."))
        self.stdout.write("")

        # 1️⃣ Update Player Points
        self.update_player_points()

        # 2️⃣ End Loans for Current Gameweek
        self.end_loans()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("🎯 Gameweek End Process Completed!"))

    # --------------------------------------------------------------------
    def update_player_points(self):
        """Fetch and update players' total points from FPL API."""
        self.stdout.write(self.style.HTTP_INFO("📊 Updating player points from FPL API..."))
        url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        response = requests.get(url)

        if response.status_code != 200:
            self.stderr.write("❌ Failed to fetch data from FPL API")
            return

        data = response.json()
        players_data = data.get("elements", [])
        updated_count = 0
        skipped_count = 0

        for p in players_data:
            first_name = p.get("first_name", "").strip()
            last_name = p.get("second_name", "").strip()
            total_points = p.get("total_points", 0)

            try:
                player = Player.objects.get(first_name=first_name, last_name=last_name)
                player.points = total_points
                player.save(update_fields=["points"])
                updated_count += 1
            except Player.DoesNotExist:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"✅ Updated points for {updated_count} players "
                               f"(skipped {skipped_count} not found)")
        )
        self.stdout.write("")

    # --------------------------------------------------------------------
    def end_loans(self):
        """End player loans scheduled for the current gameweek."""
        self.stdout.write(self.style.HTTP_INFO("🔄 Processing loan returns..."))

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
            self.stdout.write(self.style.WARNING("⚠ No loans scheduled to end this gameweek."))
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
                # restore player state
                player.is_academy_player = player.was_academy_player
                player.was_academy_player = False
                player.is_locked = player.was_locked
                player.was_locked = False
                player.team = old_team
                player.is_loan = False
                player.loan_from_team = None
                player.save()

                # mark history as ended
                history.is_loan_end = True
                history.save()

                # create return record
                TransferHistory.objects.create(
                    season=active_season,
                    player=player,
                    from_team=current_team,
                    to_team=old_team,
                    amount=Decimal("0"),
                    is_loan_end=True,
                )

                # trigger signal
                player_loan_ended.send(
                    sender=self.__class__,
                    player=player,
                    from_team=current_team,
                    to_team=old_team,
                    amount=Decimal("0"),
                    user=None,
                    is_loan=False,
                    loan_gameweek=current_gw,
                )

                ended_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"✅ Ended {ended_count} loan(s) for Gameweek {current_gw}.")
        )
