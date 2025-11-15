from django.dispatch import Signal, receiver
from django.db.models.signals import post_delete

player_signed = Signal()
contract_extended = Signal()
player_released = Signal()
player_transferred = Signal()
player_loan_ended = Signal()
weekly_bonus_applied = Signal()

@receiver(post_delete)
def delete_story_media(sender, instance, **kwargs):
    # Import inside function to avoid circular import
    from .models import Story

    if sender == Story:
        if instance.media:
            instance.media.delete(save=False)

