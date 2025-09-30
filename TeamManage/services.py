from django.utils import timezone
from .models import Bid, TransferHistory, SeasonConfig
from decimal import Decimal
from TeamManage.signals import player_signed
from django.db import transaction

def finalize_expired_bids():
    now = timezone.now()
    print(f"[BID CHECK] Running finalize_expired_bids at {now}")

    expired_bids = Bid.objects.select_for_update().filter(
        expires_at__lt=now, processed=False
    )

    if not expired_bids.exists():
        print("[BID CHECK] No expired bids found")
        return

    season = SeasonConfig.get_active_season()

    with transaction.atomic():
        for bid in expired_bids:
            # Double-check inside transaction to avoid race conditions
            if bid.processed:
                continue

            player = bid.player
            team = bid.team

        # --- Finalize transfer (free agent → team) ---
            TransferHistory.objects.create(
                season=season,
                player=player,
                from_team=None,  # Free Agent
                to_team=team,
                amount=bid.amount,
                description=f"Free Agent bid won at {bid.amount}M",
            )
            print(f"[TRANSFER] {player} -> {team} for {bid.amount}M")

            # Deduct bid amount
            team.current_balance = (team.current_balance or Decimal("0")) - (bid.amount or Decimal("0"))
            team.save(update_fields=["current_balance"])

            # Assign player to team (academy flag)
            player.team = team
            player.is_academy_player = True
            player.contract_expiry = None
            player.contract_renew_bonus = Decimal('0.0')
            player.save(update_fields=["team", "is_academy_player", "contract_expiry", "contract_renew_bonus"])
            print(f"[PLAYER UPDATED] {player} assigned to {team}")

            player_signed.send(
                sender=finalize_expired_bids,
                player=player,
                team=team,
                amount=bid.amount,
                user=None  # None → FHPL author in create_news_post
            )
            bid.processed = True  # Mark as processed
            bid.save(update_fields=["processed"])
            bid.delete()
        