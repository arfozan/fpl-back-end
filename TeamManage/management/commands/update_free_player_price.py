import requests
from django.core.management.base import BaseCommand
from TeamManage.models import Player

class Command(BaseCommand):
    help = "Update base price for players without a team (team is null) using FPL API data"

    def handle(self, *args, **kwargs):
        url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        response = requests.get(url)
        if response.status_code != 200:
            self.stderr.write("❌ Failed to fetch data from FPL API")
            return

        data = response.json()
        players_data = data.get("elements", [])

        updated_count = 0
        skipped_count = 0
        unmatched_names = []

        for p in players_data:
            first_name = p.get("first_name", "").strip()
            last_name = p.get("second_name", "").strip()
            base_price = p.get("now_cost", 0) / 10.0

            try:
                player = Player.objects.get(first_name=first_name, last_name=last_name)

                if player.team is None:
                    if player.base_price != base_price:
                        player.base_price = base_price
                        player.save(update_fields=['base_price'])
                        updated_count += 1
                else:
                    skipped_count += 1

            except Player.DoesNotExist:
                unmatched_names.append(f"{first_name} {last_name}")

        self.stdout.write(self.style.SUCCESS(f"✅ Base price updated for {updated_count} unassigned players"))
        self.stdout.write(f"⏩ Skipped {skipped_count} players with assigned teams")

        if unmatched_names:
            self.stdout.write("\n⚠️ Players from API not found in database:")
            for name in unmatched_names:
                self.stdout.write(f" - {name}")
