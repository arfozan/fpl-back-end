import os
import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from TeamManage.models import Player  # Adjust if necessary


class Command(BaseCommand):
    help = "Update the club_name and player photo using FPL API data"

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
            photo_name = p.get("photo", "").strip()

            club_name = team_map.get(team_id)
            if not club_name or not photo_name:
                continue

            photo_url = f"https://resources.premierleague.com/premierleague25/photos/players/110x140/p{photo_name}"

            try:
                player = Player.objects.get(first_name=first_name, last_name=last_name)
                player.club_name = club_name

                # Download image
                img_response = requests.get(photo_url)
                if img_response.status_code == 200:
                    file_name = os.path.basename(photo_name)
                    player.photo.save(file_name, ContentFile(img_response.content), save=False)

                player.save()
                updated_count += 1

            except Player.DoesNotExist:
                skipped_count += 1
                continue

        self.stdout.write(self.style.SUCCESS(
            f"✅ Updated club_name and photo for {updated_count} players. Skipped {skipped_count} players not found in DB."
        ))
