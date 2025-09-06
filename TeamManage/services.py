from django.utils import timezone
from .models import Bid, TransferHistory, SeasonConfig

def finalize_expired_bids():
    now = timezone.now()
    print(f"[BID CHECK] Running finalize_expired_bids at {now}")

    expired_bids = Bid.objects.filter(expires_at__lt=now)

    if not expired_bids.exists():
        print("[BID CHECK] No expired bids found")
        return

    season = SeasonConfig.get_active_season()

    for bid in expired_bids:
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
        team.current_balance -= bid.amount
        team.save(update_fields=["current_balance"])

        # Assign player to team (academy flag)
        player.team = team
        player.is_academy_player = True
        player.save(update_fields=["team", "is_academy_player"])
        print(f"[PLAYER UPDATED] {player} assigned to {team}")

        # Remove bid (auction closed)
        bid.delete()