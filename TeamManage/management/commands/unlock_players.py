from django.core.management.base import BaseCommand
from TeamManage.models import Player

class Command(BaseCommand):
    help = "Unlock all players by setting is_locked to False"

    def handle(self, *args, **kwargs):
        updated_count = Player.objects.update(is_locked=False)
        updated_count = Player.objects.update(is_transfer_lock=False)
        self.stdout.write(self.style.SUCCESS(f"Unlocked {updated_count} players."))
