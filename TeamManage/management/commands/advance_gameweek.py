from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from TeamManage.models import SeasonConfig, Team, TransferHistory

class Command(BaseCommand):
    help = "Advance to next gameweek for the active season"

    def handle(self, *args, **options):
        active_season = SeasonConfig.get_active_season()

        if not active_season:
            self.stdout.write(self.style.ERROR("❌ No active season found."))
            return

        if active_season.current_gameweek >= 38:
            active_season.is_season_active = False
            active_season.save()
            self.stdout.write(self.style.WARNING(
                f"⚠ Season {active_season.season_name} has ended at GW38 and is now deactivated."
            ))
            return

        # Increment gameweek
        active_season.current_gameweek += 1
        active_season.save()

        teams_with_counts = Team.objects.annotate(
            no_contract_count=Count('players', filter=Q(players__contract_expiry__isnull=True))
        )

        updates = []
        ten_minutes_ago = timezone.now() - timedelta(minutes=10)

        for team in teams_with_counts:
            penalty_count = 0
            players_no_contract = team.players.filter(contract_expiry__isnull=True)

            for player in players_no_contract:
                last_transfer = (
                    TransferHistory.objects
                    .filter(player=player, to_team=team)
                    .order_by('-transfer_date')
                    .first()
                )
                if last_transfer:
                    if last_transfer.transfer_date <= ten_minutes_ago:
                        penalty_count += 1
                else:
                    penalty_count += 1

            penalty = Decimal('5') * penalty_count
            new_balance = (team.current_balance or Decimal('0')) - team.weekly_wage_total - penalty
            team.current_balance = new_balance
            updates.append(team)

        Team.objects.bulk_update(updates, ['current_balance'])

        self.stdout.write(self.style.SUCCESS(
            f"✅ Advanced {active_season.season_name} to Gameweek {active_season.current_gameweek}."
        ))
