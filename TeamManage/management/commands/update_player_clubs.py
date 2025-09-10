import requests
from django.core.management.base import BaseCommand
from TeamManage.models import Player  # Adjust if your model is in a different app

class Command(BaseCommand):
    help = "Update the club_name of existing players using FPL API data"

    def handle(self, *args, **options):
        url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        response = requests.get(url)

        if response.status_code != 200:
            self.stderr.write("❌ Failed to fetch data from FPL API")
            return

        data = response.json()
        players_data = data.get("elements", [])
        teams_data = data.get("teams", [])
        team_map = {team["id"]: team["name"] for team in teams_data}

        updated_count = 0
        skipped_count = 0

        for p in players_data:
            first_name = p.get("first_name", "").strip()
            last_name = p.get("second_name", "").strip()
            team_id = p.get("team")
            club_name = team_map.get(team_id)

            if not club_name:
                continue

            try:
                player = Player.objects.get(first_name=first_name, last_name=last_name)
                player.club_name = club_name
                player.save()
                updated_count += 1
            except Player.DoesNotExist:
                skipped_count += 1
                continue

        self.stdout.write(self.style.SUCCESS(
            f"✅ Updated club_name for {updated_count} players. Skipped {skipped_count} players not found in DB."
        ))
