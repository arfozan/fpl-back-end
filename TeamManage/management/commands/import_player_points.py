import requests
from django.core.management.base import BaseCommand
from TeamManage.models import Player

class Command(BaseCommand):
    help = "Update players' total points from FPL API"

    def handle(self, *args, **options):
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

        self.stdout.write(self.style.SUCCESS(
            f"✅ Updated points for {updated_count} players (skipped {skipped_count} not found)"
        ))
