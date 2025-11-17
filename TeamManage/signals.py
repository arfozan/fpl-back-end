from django.dispatch import Signal, receiver
from django.db.models.signals import post_delete, post_save
from decimal import Decimal

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

@receiver(post_save, sender=None)
def apply_monthly_bonus(sender, instance, created, **kwargs):
    """
    Apply bonus when a MonthlyBonus record is created.
    """

    # Import here to avoid circular imports
    from .models import MonthlyBonus

    # Only process MonthlyBonus model
    if sender != MonthlyBonus:
        return

    if created:
        player = instance.player
        team = instance.team
        amount = instance.bonus_amount or Decimal("0")

        # Update player total bonus earning
        player.bonus_earning += amount
        player.save(update_fields=["bonus_earning"])

        if team:
            team.bonus_income += amount
            team.current_balance += amount
            team.save(update_fields=["bonus_income", "current_balance"])

