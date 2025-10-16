import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from TeamManage.models import Player

FPL_POSITION_MAP = {
    1: 'GK',
    2: 'DF',
    3: 'MF',
    4: 'FW',
}

class Command(BaseCommand):
    help = "Import players from FPL API with optional update mode"

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help='Update all existing players (use mid-season)'
        )

    def handle(self, *args, **options):
        update_mode = options['update']
        new_players = []

        url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        response = requests.get(url)
        if response.status_code != 200:
            self.stderr.write("❌ Failed to fetch data from FPL API")
            return

        data = response.json()
        players_data = data.get("elements", [])
        teams_data = data.get("teams", [])
        team_map = {t["id"]: t["name"] for t in teams_data}

        imported_count = 0
        updated_count = 0

        for p in players_data:
            first_name = p.get("first_name", "").strip()
            last_name = p.get("second_name", "").strip()
            base_price = p.get("now_cost", 0) / 10.0
            position_code = FPL_POSITION_MAP.get(p.get("element_type"))
            team_id = p.get("team")
            club_name = team_map.get(team_id)

            if not position_code:
                continue

            # Prepare photo filename
            photo_code = p.get("photo", "")
            filename_png = f"{first_name}_{last_name}.png".replace(" ", "_")
            filename_jpg = f"{first_name}_{last_name}.jpg".replace(" ", "_")

            # Function to get player photo
            def fetch_photo():
                # Try PNG
                url_png = f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{photo_code.replace('.jpg', '.png')}"
                r = requests.get(url_png)
                if r.status_code == 200:
                    return filename_png, r
                # Fallback to JPG
                url_jpg = f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{photo_code}"
                r = requests.get(url_jpg)
                if r.status_code == 200:
                    return filename_jpg, r
                return None, None

            try:
                player = Player.objects.get(first_name=first_name, last_name=last_name)
                if update_mode:
                    player.base_price = base_price
                    player.position = position_code
                    player.club_name = club_name

                    # Update photo only if missing or changed
                    filename, photo_response = fetch_photo()
                    if photo_response and (
                        not player.photo
                        or not player.photo.name
                        or filename != player.photo.name.split('/')[-1]
                    ):
                        player.photo.save(filename, ContentFile(photo_response.content), save=False)

                    player.save()
                    updated_count += 1

            except Player.DoesNotExist:
                new_players.append(f"{first_name} {last_name}")

                # New player → Always add
                player = Player(
                    first_name=first_name,
                    last_name=last_name,
                    base_price=base_price,
                    position=position_code,
                    club_name=club_name,
                )

                filename, photo_response = fetch_photo()
                if photo_response:
                    player.photo.save(filename, ContentFile(photo_response.content), save=True)
                else:
                    # Assign default photo if not found
                    player.photo.name = "human.png"  # path relative to MEDIA_ROOT
                    player.save()


                imported_count += 1
                new_players.append(f"{first_name} {last_name}")

        if update_mode:
            self.stdout.write(self.style.SUCCESS(f"✅ Updated {updated_count} players, added {imported_count} new players"))
            if new_players:
                self.stdout.write("\n🆕 New Players Added:")
                for name in new_players:
                    self.stdout.write(f" - {name}")
        else:
            self.stdout.write(self.style.SUCCESS(f"✅ Imported {imported_count} new players (no updates to existing ones)"))
