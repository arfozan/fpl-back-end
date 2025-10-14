import os
import time
import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.conf import settings
from TeamManage.models import Player


class Command(BaseCommand):
    help = "Update all player club names and photos from the FPL + Premier League API."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("⚽ Updating Player Clubs & Photos..."))

        url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            self.stderr.write(f"❌ Failed to fetch data from FPL API: {e}")
            return
# this is the comment to test my build
        data = response.json()
        players_data = data.get("elements", [])
        teams_data = data.get("teams", [])
        team_map = {team["id"]: team["name"] for team in teams_data}

        updated_count = 0
        skipped_count = 0
        photo_failed = 0

        for p in players_data:
            first_name = p.get("first_name", "").strip()
            last_name = p.get("second_name", "").strip()
            team_id = p.get("team")
            photo_name = p.get("photo", "").strip()
            club_name = team_map.get(team_id)

            if not club_name:
                skipped_count += 1
                continue

            # ✅ FPL player photo URL (current format)
            photo_url = None
            if photo_name:
                photo_base = os.path.splitext(photo_name)[0]
                photo_filename = f"{photo_base}.png"
                photo_url = f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{photo_filename}"

            try:
                player = Player.objects.get(first_name=first_name, last_name=last_name)
                player.club_name = club_name

                new_photo_saved = False

                # ✅ Attempt to download latest photo if available
                if photo_url:
                    try:
                        img_response = requests.get(photo_url, timeout=10)
                        if img_response.status_code == 200 and img_response.content:
                            # Delete old photo first
                            if player.photo and player.photo.name:
                                old_path = player.photo.path
                                player.photo.delete(save=False)
                                if os.path.exists(old_path):
                                    os.remove(old_path)

                            file_name = os.path.basename(photo_name)
                            if not file_name.lower().endswith(".png"):
                                file_name += ".png"

                            save_path = os.path.join("", file_name)
                            player.photo.save(save_path, ContentFile(img_response.content), save=False)
                            new_photo_saved = True
                        else:
                            photo_failed += 1
                            print(f"⚠️ Could not download image for {player.first_name} {player.last_name} ({photo_url})")
                    except requests.RequestException:
                        photo_failed += 1
                        print(f"⚠️ Request failed for {player.first_name} {player.last_name} ({photo_url})")

                # ✅ Fallback to default generic image if player has no photo at all
                if not player.photo or not player.photo.name:
                    player.photo = "default_human.png"

                # ✅ Save changes (photo only if updated)
                if new_photo_saved:
                    player.save(update_fields=["club_name", "photo"])
                else:
                    player.save(update_fields=["club_name", "photo"])

                updated_count += 1
                time.sleep(0.15)  # avoid hitting API too fast

            except Player.DoesNotExist:
                skipped_count += 1
                continue

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"✅ Updated {updated_count} players | Skipped {skipped_count} | {photo_failed} photo(s) failed."
        ))
