from rest_framework import viewsets
from .models import (Team, Player, SeasonConfig, TransferHistory,
                     Match, Bid, NewsPost, TransferWindow, TransferRequest, 
                     TeamAchievement, MaintenanceMode, LoanExtensionRequest, WeeklyBonus,
                     TeamSeasonRanks, Story, MatchPrediction, Round, MonthlyBonus)
from .serializers import (
    TeamSummarySerializer, PlayerSerializer,
    SeasonConfigSerializer, TransferHistorySerializer,
    MatchSerializer, BidSerializer, TransferWindow, NewsPostSerializer, TeamSeasonStatsSerializer,
    TransferWindowSerializer, TransferRequestSerializer, ActiveLoanSerializer,
    LoanExtensionRequestSerializer, ActiveLoanWithExtensionSerializer, WeeklyBonusSerializer,
    TeamMiniSerializer, SeasonMiniSerializer, StorySerializer, TeamPredictionSerializer, SubmitPredictionSerializer
)
from django.db import models
from django.db.models import Q, Max, Prefetch
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import generics, permissions, status
from rest_framework.decorators import action
from django.utils import timezone
from decimal import Decimal
from django.conf import settings
from rest_framework.exceptions import ValidationError
from .signals import contract_extended, player_transferred
from django.db import transaction
from django.db.models import Count
from rest_framework.pagination import PageNumberPagination
from .models import WeeklyBonus
from .utils import get_team_bonus_summary

class NewsPagination(PageNumberPagination):
    page_size = 10

@api_view(['GET'])
def get_all_teams_summary(request):
    teams = Team.objects.all()
    serializer = TeamSummarySerializer(teams, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
def team_overview(request, team_id):
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return Response({"error": "Team not found"}, status=404)
    
    active_season = SeasonConfig.get_active_season()
    current_gameweek = active_season.current_gameweek if active_season else 0

    players_qs = Player.objects.filter(team=team)
    total_weekly_wage = sum((p.weekly_wage for p in players_qs), Decimal("0"))
    total_yearly_wage = Decimal(total_weekly_wage * 38)
    current_wage_cost = total_weekly_wage * Decimal(current_gameweek)

    academy_players_count = players_qs.filter(is_academy_player=True).count()
    main_players_count = players_qs.filter(is_academy_player=False).count()

    loaned_out_count = Player.objects.filter(
        loan_from_team=team, is_loan=True, is_academy_player=False
    ).count()

    main_players_count += loaned_out_count

    top_players_qs = players_qs.order_by("-points")[:5]
    top_players_serializer = PlayerSerializer(
        top_players_qs, many=True, context={"request": request}
    )

    # Achievements
    achievements = TeamAchievement.objects.filter(team=team).prefetch_related("ranks__season")
    achievements_data = [
        {
            "blon_winning_season": ach.blon_winning_season,
            "blon_count": ach.blon_count,
            "league_champion": ach.league_champion,
            "league_runner_up": ach.league_runner_up,
            "ucl_champion": ach.ucl_champion,
            "ucl_runner_up": ach.ucl_runner_up,
            "ranks": [
                {
                    "season": r.season.season_name,
                    "league_rank": r.league_rank,
                    "ucl_rank": r.ucl_rank,
                }
                for r in ach.ranks.all()
            ]
        }
        for ach in achievements
    ]

    return Response({
        "team_name": team.name,
        "logo": request.build_absolute_uri(team.logo.url) if team.logo else None,
        "total_weekly_wage": total_weekly_wage,
        "forecast_end_balance": team.forecast_end_balance,
        "current_balance": team.current_balance,
        "total_yearly_wage": total_yearly_wage,
        "current_wage_cost": current_wage_cost,
        "total_players": main_players_count,
        "academy_players": academy_players_count,
        "achievements": achievements_data,
        "manager_name": team.manager_name,
        "manager_photo": request.build_absolute_uri(team.manager_photo.url) if team.manager_photo else None,
        "top_players": top_players_serializer.data,
    })

@api_view(['GET'])
def team_players(request, team_id):
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return Response({"error": "Team not found"}, status=404)

    position_order = {"GK": 1, "DF": 2, "MF": 3, "FW": 4}
    players_qs = Player.objects.filter(team=team)

    players_sorted = sorted(
        players_qs,
        key=lambda p: position_order.get(p.position, 99)
    )

    serializer = PlayerSerializer(players_sorted, many=True)

    return Response({
        "team_name": team.name,
        "logo": request.build_absolute_uri(team.logo.url) if team.logo else None,
        "manager_name": team.manager_name,
        "manager_photo": request.build_absolute_uri(team.manager_photo.url) if team.manager_photo else None,
        "players": serializer.data,
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_team(request):
    try:
        team = Team.objects.get(user_name=request.user)
        return Response({
            "has_team": True,
            "id": team.id,
            "username": request.user.username,
            "name": team.name,
            "manager_name": team.manager_name,
            "manager_photo": request.build_absolute_uri(team.manager_photo.url),
            "logo": request.build_absolute_uri(team.logo.url),
            "current_balance": team.current_balance
        })
    except Team.DoesNotExist:
        # User exists but has no team
        return Response({"has_team": False})
    
@api_view(['PUT', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def update_team_images(request):
    try:
        team = Team.objects.get(user_name=request.user)

        if "manager_name" in request.data:
            team.manager_name = request.data["manager_name"]

        if 'manager_photo' in request.FILES:
            team.manager_photo = request.FILES['manager_photo']

        if 'logo' in request.FILES:
            team.logo = request.FILES['logo']

        team.save()

        return Response({
            "message": "Updated successfully",
            "manager_name": team.manager_name,
            "manager_photo": request.build_absolute_uri(team.manager_photo.url),
            "logo": request.build_absolute_uri(team.logo.url),
        })

    except Team.DoesNotExist:
        return Response({"error": "Team not found"}, status=404)

class SeasonConfigViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SeasonConfig.objects.all().order_by('-id')
    serializer_class = SeasonConfigSerializer

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')

        if not user.check_password(old_password):
            return Response({"detail": "Old password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()

        return Response({"detail": "Password changed successfully."}, status=status.HTTP_200_OK)

@api_view(['GET'])
def player_details(request, player_id):
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return Response({"error": "Player not found"}, status=status.HTTP_404_NOT_FOUND)

    serializer = PlayerSerializer(player)
    return Response(serializer.data)


class TeamTransferHistoryAPIView(generics.ListAPIView):
    serializer_class = TransferHistorySerializer

    def get_queryset(self):
        team_id = self.kwargs.get('team_id')
        return TransferHistory.objects.filter(
            Q(from_team_id=team_id) | Q(to_team_id=team_id)
        ).order_by('-id')
    
class PlayerTransferHistoryAPIView(generics.ListAPIView):
    serializer_class = TransferHistorySerializer

    def get_queryset(self):
        player_id = self.kwargs['player_id']
        return TransferHistory.objects.filter(player_id=player_id).select_related("from_team", "to_team", "player", "season")

def get_serializer_context(self):
    context = super().get_serializer_context()
    context['team_id'] = self.kwargs.get('team_id')
    return context

# Define this globally or inside the view
POSITION_ORDER = {"GK": 1, "DF": 2, "MF": 3, "FW": 4}

from .utils import get_team_bonus_summary
from .models import SeasonConfig

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_team_players(request):
    user = request.user
    team = Team.objects.filter(user_name=user).first()

    if not team:
        return Response({"team": None, "players": [], "expiring_contracts_count": 0}, status=status.HTTP_200_OK)

    players_qs = (
        Player.objects
        .filter(team=team)
        .select_related("team", "loan_from_team", "contract_expiry")
    )

    total_weekly_wage = sum((p.weekly_wage for p in players_qs), Decimal("0"))
    total_yearly_wage = Decimal(total_weekly_wage * 38)

    academy_players_count = players_qs.filter(is_academy_player=True).count()
    main_players_count = players_qs.filter(is_academy_player=False).count()

    loaned_out_count = Player.objects.filter(
        loan_from_team=team,
        is_loan=True,
        was_academy_player=False
    ).count()
    main_players_count += loaned_out_count

    expiring_count = players_qs.filter(contract_expiry__isnull=True).count()

    players_sorted = sorted(
        players_qs,
        key=lambda p: POSITION_ORDER.get(p.position, 99)
    )

    players_data = PlayerSerializer(players_sorted, many=True, context={"request": request}).data
    team_data = TeamSummarySerializer(team, context={"request": request}).data

    # ✅ Get active season bonus
    active_season = SeasonConfig.objects.filter(is_season_active=True).first()
    team_bonus = 0.0
    if active_season:
        bonus_summary = get_team_bonus_summary(active_season.id, team.id)
        team_bonus = list(bonus_summary.values())[0]["bonus"] if bonus_summary else 0.0

    return Response({
        "team": team_data,
        "players": players_data,
        "expiring_contracts_count": expiring_count,
        "total_weekly_wage": float(total_weekly_wage),
        "total_yearly_wage": float(total_yearly_wage),
        "academy_players_count": academy_players_count,
        "main_players_count": main_players_count,
        "season_bonus": team_bonus, 
    }, status=status.HTTP_200_OK)

@api_view(["GET"])
def list_transfer_windows(request):
    windows = TransferWindow.objects.all().order_by('id')
    serializer = TransferWindowSerializer(windows, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_academy(request, player_id):
    # ✅ Check transfer window
    if not TransferWindow.objects.filter(is_contract_open=True).exists():
        return Response(
            {"error": "No active transfer window. Cannot toggle academy."},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        player = (
            Player.objects.select_for_update()
            .select_related("team")
            .filter(pk=player_id)
            .first()
        )
        if not player:
            return Response({"error": "Player not found"}, status=status.HTTP_404_NOT_FOUND)

        if player.is_locked:
            return Response(
                {"error": "Player is locked and cannot be toggled"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if player.is_academy_player:
            main_team_count = Player.objects.filter(
                team=player.team,
                is_academy_player=False
            ).aggregate(c=Count('id'))['c']

            if main_team_count >= 30:
                return Response(
                    {"error": "Main team already has 30 players."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        player.is_academy_player = not player.is_academy_player
        player.is_locked = True
        player.save()

    return Response({
        "id": player.id,
        "is_academy_player": player.is_academy_player,
        "is_locked": player.is_locked
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extend_contract(request, player_id):
    # 1️⃣ Check if any active transfer window exists
    current_window = TransferWindow.objects.filter(is_contract_open=True).first()
    if not current_window:
        return Response(
            {"error": "No active transfer window. Cannot extend contract."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 2️⃣ Get the player
    try:
        player = Player.objects.get(pk=player_id)
    except Player.DoesNotExist:
        return Response({"error": "Player not found"}, status=status.HTTP_404_NOT_FOUND)

    # 3️⃣ Get transfer_window_id from request
    window_id = request.data.get("transfer_window_id")
    if not window_id:
        return Response({"error": "transfer_window_id required"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        window = TransferWindow.objects.get(pk=window_id)
    except TransferWindow.DoesNotExist:
        return Response({"error": "Invalid transfer window"}, status=status.HTTP_404_NOT_FOUND)
    
    if player.is_loan:
        return Response(
            {"detail": "Player is on loan, You cant extend contract"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 4️⃣ Check the 2-id rule
    if player.contract_expiry:
        current_id = player.contract_expiry.id
    else:
        current_id = current_window.id
    
    if window.id < current_id + 2:
        return Response(
            {"detail": "Minimum Contract should be 1 year (prior 2 transfer window)"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 5️⃣ Extend contract
    had_contract = bool(player.contract_expiry)  # check before overwriting
    player.contract_expiry = window

    if had_contract:
        player.contract_renew_bonus = (player.contract_renew_bonus or Decimal("0")) + Decimal("0.5")
    
    player.save(update_fields=["contract_expiry", "contract_renew_bonus"])

    contract_extended.send(
        sender=Player,
        player=player,
        window=window,
        user=request.user
    )

    return Response({
        "id": player.id,
        "contract_expiry": str(window),
        "contract_renew_bonus": str(player.contract_renew_bonus or "0")
    })

# 1️⃣ Team-wise matches (all seasons)
@api_view(['GET'])
def team_matches(request, team_id):
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)

    # get optional season filter
    season_id = request.GET.get("season")

    matches = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team)
    )

    if season_id:
        matches = matches.filter(round__season_id=season_id)

    matches = matches.order_by("-id")

    serializer = MatchSerializer(matches, many=True)
    return Response(serializer.data)

# ✅ Overall stats for a team
@api_view(["GET"])
def team_overall_stats(request, team_id):
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)

    serializer = TeamSummarySerializer(team)
    return Response(serializer.data)

@api_view(["GET"])
def season_team_details(request, season_id, team_id):
    """Return all matches of a team in a season (optionally filter by opponent)"""
    opponent_id = request.query_params.get("opponent_team_id")

    qs = Match.objects.filter(
        round__season_id=season_id
    ).filter(
        models.Q(home_team_id=team_id) | models.Q(away_team_id=team_id)
    ).select_related("round", "home_team", "away_team")

    if opponent_id and opponent_id != "all":
        qs = qs.filter(
            models.Q(home_team_id=opponent_id) | models.Q(away_team_id=opponent_id)
        )

    matches = MatchSerializer(qs, many=True).data

    # 🔧 Ensure TeamSeasonStats exists for this team & season
    stats, _ = TeamSeasonRanks.objects.get_or_create(
        season_id=season_id,
        team_id=team_id,
        defaults={"wins": 0, "draws": 0, "losses": 0},
    )

    stats_data = TeamSeasonStatsSerializer(stats).data

    return Response({
        "season_id": season_id,
        "team_id": team_id,
        "stats": stats_data,
        "matches": matches,
    })

@api_view(["GET"])
def players_list(request):
    players = Player.objects.all().order_by("last_name")
    serializer = PlayerSerializer(players, many=True)
    return Response(serializer.data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_bid(request):
    player_id = request.data.get("player_id")
    amount = Decimal(str(request.data.get("amount", "0")))

    user = request.user
    if not user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

    try:
        team = Team.objects.get(user_name=user)
        player = Player.objects.get(id=player_id)
        season = SeasonConfig.get_active_season()
    except Team.DoesNotExist:
        return Response({"error": "No team found for this user"}, status=400)
    except Player.DoesNotExist:
        return Response({"error": "Invalid player"}, status=400)

    # Free agent check
    if player.team:
        return Response(
            {"error": "This player already belongs to a team and cannot be bid on."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # --- Determine minBid ---
    existing_bid = Bid.objects.filter(player=player).first()
    
    if not existing_bid:
    # First bid logic
        active_window = TransferWindow.objects.filter(is_active=True).first()
        if not active_window:
            raise ValidationError({"error": ["No active transfer window. New bidding is closed."]})

        if player.contract_expiry_id == active_window.id:
            min_bid = Decimal("0")  # free transfer for first bid
        else:
            min_bid = player.base_price
    else:
        # There is already a bid → next bid must be higher
        min_bid = existing_bid.amount + Decimal("0.1")

    # --- Validation ---
    if amount < min_bid:
        return Response(
            {"error": f"Bid must be at least {amount}M"},
            status=status.HTTP_400_BAD_REQUEST
        )

    increment = Decimal("0.1") 
    min_bid = Decimal(str(min_bid))

    if existing_bid:
        base = Decimal(str(existing_bid.amount))
    else:
        base = min_bid

    diff = amount - base
    steps = diff / increment

    if steps != steps.to_integral_value():
        return Response(
            {"error": f"Bid must increase in {steps}M steps"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # --- Forecast balance check ---
    forecast_end_balance = team.forecast_end_balance
    current_gameweek = season.current_gameweek
    new_bid_cost = amount + (player.weekly_wage * Decimal(38 - current_gameweek))

    active_bids = Bid.objects.filter(team=team, player__team__isnull=True)
    active_bids_cost = Decimal("0")
    for b in active_bids:
        if b.player_id == player.id:
            continue
        active_bids_cost += b.amount + (b.player.weekly_wage * Decimal(38 - current_gameweek))

    total_future_commitment = new_bid_cost + active_bids_cost
    if forecast_end_balance - total_future_commitment <= Decimal("-15"):
        return Response(
            {"error": "Insufficient forecast balance, cannot place bid"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --- Save bid ---
    if existing_bid:
        existing_bid.team = team
        existing_bid.amount = amount
        existing_bid.expires_at = timezone.now() + settings.BID_EXPIRY
        existing_bid.save(update_fields=["team", "amount", "expires_at"])
        return Response(
            {"message": "Bid updated successfully", "bid_id": existing_bid.id},
            status=status.HTTP_200_OK
        )

    bid = Bid.objects.create(
        team=team,
        player=player,
        amount=amount,
        expires_at=timezone.now() + settings.BID_EXPIRY
    )

    return Response(
        {
            "message": "Bid placed successfully",
            "bid_id": bid.id
        },
        status=status.HTTP_201_CREATED,
    )

@api_view(["GET"])
def free_agents(request):
    players = Player.objects.filter(team__isnull=True)
    serializer = PlayerSerializer(players, many=True)
    return Response(serializer.data)

@permission_classes([IsAuthenticated])
@api_view(["GET"])
def active_bids(request):
    # Get the latest bid ID per player
    latest_bid_ids = (
        Bid.objects.values("player_id")
           .annotate(latest_id=Max("id"))
           .values_list("latest_id", flat=True)
    )

    # Fetch Bid objects using these IDs
    bids = Bid.objects.filter(id__in=latest_bid_ids).order_by("-expires_at")

    serializer = BidSerializer(bids, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(["GET"])
def current_status(request):
    # Get active season
    season = SeasonConfig.get_active_season()
    season_data = None
    if season:
        season_data = {
            "id": season.id,
            "season_name": season.season_name,
            "current_gameweek": season.current_gameweek if season.current_gameweek > 0 else None,
        }

    # Get active transfer window
    transfer_window = TransferWindow.objects.filter(is_active=True).first()
    transfer_window_data = None
    if transfer_window:
        transfer_window_data = {
            "name": str(transfer_window),  # e.g. "Summer 2026"
            "season": transfer_window.season,
            "year": transfer_window.year,
            "deadline": transfer_window.free_transfer_deadline
        }

    return Response({
        "season": season_data,
        "transfer_window": transfer_window_data
    })

class NewsPostListCreateView(generics.ListCreateAPIView):
    queryset = NewsPost.objects.all().order_by('-date_posted')
    serializer_class = NewsPostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = NewsPagination
    parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

class NewsPostDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = NewsPost.objects.all()
    serializer_class = NewsPostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = NewsPagination

# Personal Deal View
from rest_framework.permissions import BasePermission
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_team(request):
    team = Team.objects.filter(user=request.user).first()
    if not team:
        return Response({"detail": "No team found"}, status=404)
    return Response(TeamSummarySerializer(team).data)

class IsTeamManagerOfFromTeam(BasePermission):
    """
    Allow action if request.user is manager/admin of transfer_request.from_team
    You must adapt `is_manager` check to your Team/User relation.
    """
    def has_object_permission(self, request, view, obj):
        # allow if the user is the sender or is a manager of the from_team
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        # Only the manager of the from_team may accept/reject
        return obj.from_team and obj.from_team.user_name == request.user

class TransferRequestViewSet(viewsets.ModelViewSet):
    serializer_class = TransferRequestSerializer
    permission_classes = [IsAuthenticated]  # add default perms as needed
    def get_queryset(self):
        TransferRequest.objects.filter(expires_at__lt=timezone.now()).delete()
        user = self.request.user

        try:
            team = Team.objects.get(user_name=user)
        except Team.DoesNotExist:
            return TransferRequest.objects.none()

        qs = TransferRequest.objects.select_related("player", "from_team", "to_team")
        qtype = self.request.query_params.get("type")
        if qtype == "incoming":
            return qs.filter(to_team=team)      
        elif qtype == "outgoing":
            return qs.filter(from_team=team)    
        return qs.filter(Q(from_team=team) | Q(to_team=team))

    def perform_create(self, serializer):
        user_team = getattr(self.request.user, "team", None)
        if not user_team:
            raise ValidationError("Logged-in user is not assigned to a team.")
        
        has_contract_open = TransferWindow.objects.filter(is_contract_open = True).first()
        if not has_contract_open:
            raise ValidationError({"error":["Transfer is Closed Totally."]})
        player_id = self.request.data.get("player")
        is_loan = self.request.data.get("is_loan") 
        is_loan = str(is_loan).lower() in ["true", "1", "yes"]
        player = Player.objects.get(pk=player_id)
        if player.is_transfer_lock and not is_loan: 
            raise ValidationError({"error": ["Player already transferred once in this Transfer Window."]})
        
        current_season = SeasonConfig.objects.filter(is_season_active=True).first()
        if not current_season:
            raise ValidationError("No active season.")
        current_gameweek = current_season.current_gameweek

        # ---- New offer details ----
        new_offer_amount = Decimal(self.request.data.get("amount", "0"))
        new_player_wage = player.weekly_wage * Decimal(38 - current_gameweek)

        # ---- Running commitments ----
        running_commitments = Decimal("0")

        # 1️⃣ Pending transfer requests already sent by this team
        pending_transfers = TransferRequest.objects.filter(
            to_team=user_team, status=TransferRequest.STATUS_PENDING
        ).select_related("player")
        for tr in pending_transfers:
            remaining_wage = tr.player.weekly_wage * Decimal(38 - current_gameweek)
            running_commitments += tr.amount + remaining_wage

        # Active bids (unexpired) for this team
        active_bids = Bid.objects.filter(
            team=user_team,
            expires_at__gt=timezone.now()
        ).select_related("player")  # so we can access player in loop

        active_bids_total = Decimal("0")
        for bid in active_bids:
            # Calculate remaining wage for the season
            remaining_wage = bid.player.weekly_wage * Decimal(38 - current_gameweek)
            # Add both the current bid amount AND the future wage
            active_bids_total += bid.amount + remaining_wage

        running_commitments += active_bids_total

        # ---- Forecast check ----
        forecast_end_balance = user_team.forecast_end_balance
        total_future_commitment = running_commitments + new_offer_amount + new_player_wage

        if forecast_end_balance - total_future_commitment <= Decimal("-15"):
            raise ValidationError({
                "Error": ["Insufficient balance. Cannot place this transfer request."]
            }
            )

        serializer.save(
            created_by=self.request.user,
            to_team=user_team,
            from_team=player.team,      # <-- auto-fill from player
            season=current_season       # <-- optional but common
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return super().create(request, *args, **kwargs)
    
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def cancel(self, request, pk=None):
        tr = self.get_object()
        # Only the team that SENT the request (to_team manager) can cancel
        try:
            team = Team.objects.get(user_name=request.user)
        except Team.DoesNotExist:
            return Response({"detail": "You are not assigned to a team."},
                            status=status.HTTP_403_FORBIDDEN)

        if tr.to_team != team:
            return Response({"detail": "Not allowed to cancel this request."},
                            status=status.HTTP_403_FORBIDDEN)

        if tr.status != TransferRequest.STATUS_PENDING:
            return Response({"detail": "Only pending requests can be cancelled."},
                            status=status.HTTP_400_BAD_REQUEST)

        tr.status = TransferRequest.STATUS_REJECTED
        tr.save(update_fields=["status", "updated_at"])
        tr.delete()
        return Response({"detail": "Transfer request cancelled."},
                        status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsTeamManagerOfFromTeam])
    def accept(self, request, pk=None):
        tr = self.get_object()
        if tr.status != TransferRequest.STATUS_PENDING:
            return Response({"detail": "TransferRequest not pending."}, status=status.HTTP_400_BAD_REQUEST)
        
        has_contract_open = TransferWindow.objects.filter(is_contract_open = True).first()
        if not has_contract_open:
            raise ValidationError({"error":["Transfer is Closed Totally."]})
        
        # check contract expiry first
        player = tr.player  # or tr.player_id if you store differently
        if not player.contract_expiry:
            return Response(
                {"detail": "Please define contract length of player before transfer."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            th = accept_transfer_request(tr, accepted_by=request.user)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # return created TransferHistory data (you can use serializer)
        return Response({"detail":"Accepted","transfer_history_id": th.id}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def reject(self, request, pk=None):
        tr = self.get_object()
        tr.status = TransferRequest.STATUS_REJECTED
        tr.save(update_fields=["status","updated_at"])
        tr.delete()
        return Response({"detail": "Rejected."}, status=status.HTTP_200_OK)

from django.db import transaction
def accept_transfer_request(tr: TransferRequest, accepted_by):
    from decimal import Decimal
    from django.utils import timezone

    with transaction.atomic():
        # Lock player and teams to prevent race conditions
        player = Player.objects.select_for_update().get(pk=tr.player.pk)
        from_team = Team.objects.select_for_update().get(pk=tr.from_team.pk) if tr.from_team else None
        to_team = Team.objects.select_for_update().get(pk=tr.to_team.pk)

        # Re-validate server-side conditions
        if tr.status != TransferRequest.STATUS_PENDING:
            raise ValidationError("Request not pending.")
        if player.team != from_team:
            raise ValidationError("Player no longer belongs to the expected team.")
        if tr.is_loan and player.is_loan:
            raise ValidationError("Player already on loan.")
        amount = tr.amount or Decimal("0")

        # Create TransferHistory (this model's save handles player/team updates)
        th = TransferHistory.objects.create(
            season = tr.season or SeasonConfig.objects.filter(is_season_active=True).first(),
            player = player,
            from_team = from_team,
            to_team = to_team,
            amount = amount,
            description = tr.message,
            transfer_date = timezone.now(),
            is_loan = tr.is_loan,
            loan_gameweek = tr.loan_gameweek,
            to_loan = tr.is_loan,
        )

        # --- Update player state ---
        if tr.is_loan:
            # Snapshot academy state before moving
            player.was_academy_player = player.is_academy_player
            player.was_locked = player.is_locked
            player.is_locked = False
            player.is_loan = True
            player.loan_from_team = from_team
            player.team = to_team
            player.is_academy_player = False
        else:
            player.team = to_team
            player.is_loan = False
            player.loan_from_team = None
            player.was_locked = False
            player.is_locked = False
            player.is_academy_player = True
            player.was_academy_player = False
            player.is_transfer_lock = True
            player.contract_renew_bonus = Decimal(0.0)
            player.contract_expiry = None

        player.save(update_fields=["team", "is_loan", "loan_from_team", "was_locked", 
                                   "is_locked", "is_academy_player", "was_academy_player", 
                                   "is_transfer_lock", "contract_renew_bonus", "contract_expiry"])

        # --- Update balances ---
        if from_team:
            from_team.current_balance = (from_team.current_balance or Decimal("0")) + amount
            from_team.save(update_fields=["current_balance"])
        if to_team:
            to_team.current_balance = (to_team.current_balance or Decimal("0")) - amount
            to_team.save(update_fields=["current_balance"])

        # Mark request accepted
        tr.status = TransferRequest.STATUS_ACCEPTED
        tr.save(update_fields=["status", "updated_at"])
        tr.delete()

        player_transferred.send(
            sender=accept_transfer_request,
            player=player,
            from_team=from_team,
            to_team=to_team,
            amount=amount,
            is_loan=tr.is_loan,
            loan_gameweek=tr.loan_gameweek,
            user=accepted_by,
)
        return th
    
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def available_players(request):
    user_team = Team.objects.filter(user_name=request.user).first()

    qs = Player.objects.filter(team__isnull=False, is_loan=False)

    if user_team:
        qs = qs.exclude(team=user_team)

    data = [
        {
            "id": p.id,
            "full_name": p.first_name + " " + p.last_name,
            "photo": request.build_absolute_uri(p.photo.url) if p.photo else None,
            "club": p.club_name,
            "team": p.team.name if p.team else None,
            "position": p.position,
            "points": p.points,
        }
        for p in qs
    ]
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def release_player(request, player_id):
    try:
        player = Player.objects.get(pk=player_id)
    except Player.DoesNotExist:
        return Response({"error": "Player not found"}, status=status.HTTP_404_NOT_FOUND)

    # ✅ Check if there is an open transfer window
    active_window = TransferWindow.objects.filter(is_contract_open=True).first()
    if not active_window:
        return Response(
            {"error": "No contract-open transfer window available. Cannot release player."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if player.team is None:
        return Response(
            {"error": "Player is free agent"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ✅ Check player rules
    if player.base_price != Decimal("0.0"):
        return Response(
            {"error": "Only Inactive players can be released."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if getattr(player, "is_loan", False):
        return Response(
            {"error": "Loaned players cannot be released."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ✅ Get current active season
    active_season = SeasonConfig.get_active_season()
    if not active_season:
        return Response(
            {"error": "No active season configured. Cannot release player."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ✅ Save old team before nulling
    old_team = player.team

    # ✅ Update player fields on release
    player.is_locked = False
    player.was_locked = False
    player.is_transfer_lock = False
    player.team = None
    player.contract_renew_bonus = Decimal("0.0")
    player.is_academy_player = False
    player.was_academy_player = False
    player.contract_expiry = active_window
    player.save()

    # ✅ Create TransferHistory entry
    TransferHistory.objects.create(
        season=active_season,
        player=player,
        from_team=old_team,
        to_team=None,  # released → free agent
        amount=Decimal("0.0"),
        transfer_date=timezone.now(),
        is_loan=False,
        loan_gameweek=None,
        is_loan_end=False,
        description="Player Released"
    )

    return Response({
        "id": player.id,
        "released": True,
        "team": None,
        "contract_expiry": active_window.id,
        "season": active_window.season,
        "year": active_window.year,
        "transfer_history_created": True
    })

@api_view(["GET"])
def maintenance_status(request):
    mode = MaintenanceMode.objects.first()
    if mode and mode.is_active:
        return Response({"maintenance": True, "message": mode.message})
    return Response({"maintenance": False})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_loan_players(request):
    # 1️⃣ Ensure contract window open
    if not TransferWindow.objects.filter(is_contract_open=True).exists():
        return Response({"detail": "No active transfer window open."}, status=400)

    # 2️⃣ Get manager’s team
    try:
        team = Team.objects.get(user_name=request.user)
    except Team.DoesNotExist:
        return Response({"detail": "You are not assigned to any team."}, status=403)

    # 3️⃣ Fetch active loans
    active_loans = TransferHistory.objects.filter(
        to_team=team,
        is_loan=True,
        is_loan_end=False
    )

    serializer = ActiveLoanSerializer(active_loans, many=True)
    serializer = ActiveLoanWithExtensionSerializer(active_loans, many=True)
    return Response(serializer.data)

class LoanExtensionRequestViewSet(viewsets.ModelViewSet):
    serializer_class = LoanExtensionRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        try:
            user_team = Team.objects.get(user_name=user)
        except Team.DoesNotExist:
            return LoanExtensionRequest.objects.none()

        # Include both sides: the parent team and the loaning team
        return LoanExtensionRequest.objects.filter(
            Q(transfer__from_team=user_team) | Q(requested_by=user_team)
        ).distinct()

    def perform_create(self, serializer):
        user_team = Team.objects.get(user_name=self.request.user)
        serializer.save(requested_by=user_team)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        loan_request = self.get_object()
        original_team = loan_request.transfer.from_team
        current_team = loan_request.transfer.to_team
        amount = loan_request.amount or 0

        # ensure only original team can approve
        if original_team.user_name != request.user:
            return Response({"error": "Only original team can approve."}, status=status.HTTP_403_FORBIDDEN)
        if current_team.current_balance-Decimal(15) < amount:
            return Response({"error": "Requesting team does not have enough balance."}, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            # Update loan extension request
            loan_request.is_approved = True
            loan_request.responded_at = timezone.now()
            loan_request.transfer.loan_gameweek = loan_request.new_loan_gameweek
            loan_request.transfer.save()
            loan_request.save()

            # Update team balances
            current_team.current_balance -= amount
            current_team.save()
            
            original_team.current_balance += amount
            original_team.save()

            # Optionally, remove the request after approval
            loan_request.delete()

        return Response({"status": "approved", "new_loan_gameweek": loan_request.new_loan_gameweek, "amount_transferred": amount})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        loan_request = self.get_object()
        original_team = loan_request.transfer.from_team

        if original_team.user_name != request.user:
            return Response({"error": "Only original team can reject."}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            loan_request.is_approved = False
            loan_request.responded_at = timezone.now()
            loan_request.save()
            loan_request.delete()
        return Response({"status": "rejected"}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        loan_request = self.get_object()
        requesting_team = loan_request.requested_by

        # Only the requesting team can cancel
        if requesting_team.user_name != request.user:
            return Response({"error": "Only the requesting team can cancel this request."}, status=status.HTTP_403_FORBIDDEN)

        # Only allow cancel if the request is still pending
        if loan_request.is_approved is not None:
            return Response({"error": "Cannot cancel a request that has already been approved or rejected."}, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            loan_request.delete()

        return Response({"status": "cancelled"}, status=status.HTTP_200_OK)

@api_view(["GET"])
def season_bonus_view(request, season_id):
    team_id = request.query_params.get("team")
    bonuses = WeeklyBonus.objects.filter(season_id=season_id).order_by("gameweek")

    if team_id:
        team_id_int = int(team_id)
        # filter WeeklyBonus to only include relevant teams or players
        bonuses = bonuses.filter(
            Q(highest_point_teams__id=team_id_int) |
            Q(highest_point_players__team__id=team_id_int) |
            Q(highest_gk_players__team__id=team_id_int) |
            Q(highest_df_players__team__id=team_id_int) |
            Q(highest_mf_players__team__id=team_id_int) |
            Q(highest_fw_players__team__id=team_id_int) |
            Q(special_bonus_players__team__id=team_id_int)
        ).distinct()

        # Use Prefetch to filter M2M properly for the serializer
        bonuses = bonuses.prefetch_related(
            Prefetch('highest_point_teams', queryset=Team.objects.filter(id=team_id_int)),
            Prefetch('highest_point_players', queryset=Player.objects.filter(Q(team_id=team_id_int) | Q(team__isnull=True))),
            Prefetch('highest_gk_players', queryset=Player.objects.filter(Q(team_id=team_id_int) | Q(team__isnull=True))),
            Prefetch('highest_df_players', queryset=Player.objects.filter(Q(team_id=team_id_int) | Q(team__isnull=True))),
            Prefetch('highest_mf_players', queryset=Player.objects.filter(Q(team_id=team_id_int) | Q(team__isnull=True))),
            Prefetch('highest_fw_players', queryset=Player.objects.filter(Q(team_id=team_id_int) | Q(team__isnull=True))),
            Prefetch('special_bonus_players', queryset=Player.objects.filter(Q(team_id=team_id_int) | Q(team__isnull=True))),
        )

    serializer = WeeklyBonusSerializer(bonuses, many=True, context={"team_id": team_id})
    total_bonus = get_team_bonus_summary(season_id, team_id)

    monthly_qs = MonthlyBonus.objects.filter(season_id=season_id)

    if team_id:
        monthly_qs = monthly_qs.filter(team_id=team_id_int)

    monthly_qs = monthly_qs.order_by("-id")
    monthly_bonus_data = [
        {
            "id": mb.id,
            "season": mb.season.season_name,
            "month": mb.get_month_display(),
            "team": mb.team.name if mb.team else "Free Agent",
            "team_id": mb.team.id if mb.team else None,
            "player": f"{mb.player.first_name} {mb.player.last_name}",
            "photo": mb.player.photo.url if mb.player.photo else None,
            "bonus_amount": float(mb.bonus_amount),
            "category": mb.get_category_display(),
        }
        for mb in monthly_qs
    ]

    return Response({
        "season_id": season_id,
        "team_id": team_id,
        "total_bonus": total_bonus,
        "weekly_details": serializer.data,
        "monthly_bonus": monthly_bonus_data,
    })

class TeamListAPIView(generics.ListAPIView):
    queryset = Team.objects.all().order_by('id')
    serializer_class = TeamMiniSerializer

@api_view(["GET"])
def league_table(request):
    season_id = request.query_params.get("season_id")
    if not season_id:
        return Response({"error": "season_id is required"}, status=400)

    try:
        season = SeasonConfig.objects.get(id=season_id)
    except SeasonConfig.DoesNotExist:
        return Response({"error": "Invalid season_id"}, status=404)

    stats = TeamSeasonRanks.objects.filter(season=season)

    # Sort: Points ↓, Goal Diff ↓, Goals For ↓
    sorted_stats = sorted(
        stats,
        key=lambda s: (s.points, s.goals_for),
        reverse=True
    )

    data = [
        {
            "rank": i + 1,
            "id": s.team.id,
            "team": s.team.name,
            "logo": s.team.logo.url if s.team.logo else None,
            "played": s.total_matches,
            "wins": s.wins,
            "draws": s.draws,
            "losses": s.losses,
            "goals_for": s.goals_for,
            "goals_against": s.goals_against,
            "points": s.points,
        }
        for i, s in enumerate(sorted_stats)
    ]

    return Response({
        "season": season.season_name,
        "table": data
    })

class StoryViewSet(viewsets.ModelViewSet):
    serializer_class = StorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Story.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        story = serializer.save(user=self.request.user)

        # enforce max 20 stories per user
        user_stories = Story.objects.filter(user=self.request.user).order_by("-created_at")
        if user_stories.count() > 20:
            extra_stories = user_stories[20:]  # keep latest 20

            for s in extra_stories:
                if s.media:
                    s.media.delete(save=False)  # delete file from storage
                s.delete()

from django.contrib.auth import get_user_model
User = get_user_model()
@api_view(["GET"])
def stories_feed(request):
    users = User.objects.all()
    feed = []

    for user in users:
        user_stories = Story.objects.filter(user=user).order_by("-created_at")[:20]

        if user_stories.exists():
            feed.append({
                "user": {
                    "id": user.id,
                    "name": getattr(user, "name", user.username),
                    "logo": getattr(user, "logo", None), 
                },
                "stories": StorySerializer(user_stories, many=True).data
            })

    return Response(feed)

class NextRoundPredictionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_next_round(self):
        season = SeasonConfig.get_active_season()
        if not season:
            return None, "No active season found."

        next_round_num = season.current_gameweek + 1

        round_obj = Round.objects.filter(
            season=season, round_number=next_round_num
        ).first()

        if not round_obj:
            return None, "No upcoming round found."

        return round_obj, None

    def post(self, request):
        round_obj, err = self.get_next_round()
        if err:
            return Response({"error": err}, status=404)

        # Already submitted?
        if MatchPrediction.objects.filter(
            user=request.user, round=round_obj
        ).exists():
            return Response(
                {"error": "Predictions already submitted for this round."},
                status=400
            )

        serializer = SubmitPredictionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        predictions_data = serializer.validated_data["predictions"]

        if len(predictions_data) == 0:
            return Response(
                {"error": "You must select at least one prediction."},
                status=400
            )

        valid_choices = ["HOME", "AWAY", "DRAW"]
        match_ids = list(round_obj.matches.values_list("id", flat=True))

        try:
            with transaction.atomic():
                for p in predictions_data:
                    match_id = p.get("match")
                    choice = p.get("choice", "")

                    # ✅ Normalize
                    choice = choice.strip().upper()

                    if match_id not in match_ids:
                        return Response({"error": "Invalid match ID."}, status=400)

                    if choice not in valid_choices:
                        return Response({"error": f"Invalid choice {choice}."}, status=400)

                    match_obj = Match.objects.get(id=match_id)

                    MatchPrediction.objects.create(
                        user=request.user,
                        round=round_obj,
                        match=match_obj,
                        choice=choice
                    )
        except Exception as e:
            return Response({"error": str(e)}, status=400)

        return Response({"success": "Predictions submitted."}, status=201)

class PredictionDashboardView(APIView):
    # permission_classes = [IsAuthenticated]

    # ---------------------------------------------------------------------
    # CURRENT ROUND DATA
    # ---------------------------------------------------------------------
    def get_current_round_data(self, user, season):
        current_gw = season.current_gameweek
        round_obj = Round.objects.filter(season=season, round_number=current_gw).first()
        if not round_obj:
            return None

        predictions = MatchPrediction.objects.filter(user=user, round=round_obj)
        if not predictions.exists():
            return None

        data = []
        round_bonus = Decimal("0")

        for p in predictions:
            match = p.match

            # ✅ If round NOT ended → show match in progress
            if not round_obj.is_ended:
                data.append({
                    "match_id": match.id,
                    "home": match.home_team.name,
                    "away": match.away_team.name,
                    "choice": p.choice,
                    "status": "in_progress",
                    "is_correct": None,
                    "reward": None,
                })

            # ✅ Round ended → show correctness + reward
            else:
                data.append({
                    "match_id": match.id,
                    "home": match.home_team.name,
                    "away": match.away_team.name,
                    "choice": p.choice,
                    "status": "finished",
                    "is_correct": p.is_correct,
                    "reward": str(p.rewarded_amount),
                })
                round_bonus += p.rewarded_amount

        total_bonus = user.team.prediction_bonus_total

        return {
            "round_number": current_gw,
            "status": "finished" if round_obj.is_ended else "pending",
            "predictions": data,
            "round_bonus": str(round_bonus) if round_obj.is_ended else None,
            "total_bonus": str(total_bonus),
        }

    # ---------------------------------------------------------------------
    # NEXT ROUND DATA
    # ---------------------------------------------------------------------
    def get_next_round_data(self, user, season):
        next_gw = season.current_gameweek + 1
        round_obj = Round.objects.filter(season=season, round_number=next_gw).first()
        if not round_obj:
            return None

        matches = round_obj.matches.filter(
            home_team__isnull=False,
            away_team__isnull=False
        )

        # ✅ Already submitted predictions?
        preds = MatchPrediction.objects.filter(user=user, round=round_obj)
        already = preds.exists()

        if already:
            submitted = []
            for p in preds:
                submitted.append({
                    "match_id": p.match.id,
                    "home": p.match.home_team.name,
                    "away": p.match.away_team.name,
                    "choice": p.choice,
                })

            return {
                "round_number": next_gw,
                "already_submitted": True,
                "submitted": submitted,
            }

        # ✅ Fresh matches to pick from
        matches_data = [
            {
                "id": m.id,
                "home_team_name": m.home_team.name,
                "away_team_name": m.away_team.name
            }
            for m in matches
        ]

        return {
            "round_number": next_gw,
            "already_submitted": False,
            "matches": matches_data,
        }

    # ---------------------------------------------------------------------
    # MAIN GET RESPONSE
    # ---------------------------------------------------------------------
    def get(self, request):
        season = SeasonConfig.get_active_season()
        if not season:
            return Response({"error": "No active season"}, status=400)

        user = request.user

        current_round_data = self.get_current_round_data(user, season)
        next_round_data = self.get_next_round_data(user, season)

        # ✅ Always send total bonus at top-level (critical fix)
        total_bonus = str(user.team.prediction_bonus_total)

        # ✅ Always send season info (helps frontend)
        season_info = {
            "current_gameweek": season.current_gameweek
        }

        return Response({
            "season": season_info,
            "total_bonus": total_bonus,           # ✅ Always present
            "current_round": current_round_data,   # can be None
            "next_round": next_round_data,
        })
    
class PredictionOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        season_name = request.GET.get("season")
        round_number = request.GET.get("round")

        # Get season
        if season_name:
            season = SeasonConfig.objects.filter(season_name=season_name).first()
            if not season:
                return Response({"error": "Season not found"}, status=404)
        else:
            season = SeasonConfig.get_active_season()
            if not season:
                return Response({"error": "No active season"}, status=400)

        # Determine which rounds are allowed to view
        current_gw = season.current_gameweek

        # Filter rounds
        round_filter = {"round__season": season}

        if round_number:
            round_number = int(round_number)
            # Lock future rounds
            if round_number > current_gw:
                return Response({
                    "error": "Predictions for future rounds are locked"
                }, status=403)
            round_filter["round__round_number"] = round_number
        else:
            # If no specific round is requested, only include rounds <= current
            round_filter["round__round_number__lte"] = current_gw

        # Query predictions
        qs = MatchPrediction.objects.filter(**round_filter).select_related(
            "user", "match", "match__home_team", "match__away_team", "round"
        )

        # Serialize
        predictions = TeamPredictionSerializer(qs, many=True).data

        # Leaderboard
        leaderboard_raw = (
            qs.values(
                "user",
                "user__team__manager_name",
                "user__team__name",
            )
            .annotate(
                total=Count("id"),
                correct=Count("id", filter=Q(is_correct=True)),
                wrong=Count("id", filter=Q(is_correct=False)),
            )
        )

        leaderboard = []
        for row in leaderboard_raw:
            total = row["total"]
            correct = row["correct"]
            acc = (correct / total * 100) if total > 0 else 0

            leaderboard.append({
                "manager_name": row["user__team__manager_name"],
                "team_name": row["user__team__name"],
                "total_predictions": total,
                "correct_predictions": correct,
                "wrong_predictions": row["wrong"],
                "accuracy_percent": round(acc, 2),
            })

        leaderboard = sorted(
            leaderboard, key=lambda x: x["accuracy_percent"], reverse=True
        )

        return Response({
            "season": season.season_name,
            "round": round_number if round_number else None,
            "predictions": predictions,
            "leaderboard": leaderboard,
        })

@api_view(["GET"])
def list_rounds(request):
    season_name = request.GET.get("season")
    if not season_name:
        return Response({"error": "season is required"}, status=400)

    season = SeasonConfig.objects.filter(season_name=season_name).first()
    if not season:
        return Response({"error": "Season not found"}, status=404)

    rounds = Round.objects.filter(season=season).order_by("round_number")

    data = [
        {
            "id": r.id,
            "round_number": r.round_number,
            "is_ended": r.is_ended,
            "date": r.date,
        }
        for r in rounds
    ]
    return Response(data)

@api_view(["GET"])
def season_fixtures(request):
    # ---------------------------------------------------
    # 1. Resolve season
    # ---------------------------------------------------
    season_id = request.query_params.get("season_id")

    if season_id:
        try:
            season = SeasonConfig.objects.get(id=season_id)
        except SeasonConfig.DoesNotExist:
            return Response({"error": "Invalid season_id"}, status=404)
    else:
        season = SeasonConfig.objects.order_by("-id").first()
        if not season:
            return Response({"error": "No seasons found"}, status=404)

    # ---------------------------------------------------
    # 2. Optional team filter
    # ---------------------------------------------------
    team_id = request.query_params.get("team_id")
    team_filter = None

    if team_id:
        try:
            team_filter = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return Response({"error": "Invalid team_id"}, status=404)

    # ---------------------------------------------------
    # 3. Fetch rounds for the season
    # ---------------------------------------------------
    rounds = (
        Round.objects.filter(season=season)
        .order_by("round_number")
    )

    # ---------------------------------------------------
    # 4. Build response structure
    # ---------------------------------------------------
    response_data = {
        "season_id": season.id,
        "season_name": season.season_name,
        "team_filter": team_filter.name if team_filter else "all",
        "team_filter_logo": (
            team_filter.logo.url if team_filter and team_filter.logo else None
        ),
        "rounds": []
    }

    # ---------------------------------------------------
    # 5. Loop through each round and collect matches
    # ---------------------------------------------------
    for r in rounds:
        # Always use select_related for performance
        matches_qs = r.matches.select_related(
            "home_team", "away_team"
        )

        # Apply team filter if provided
        if team_filter:
            matches_qs = matches_qs.filter(
                models.Q(home_team=team_filter) |
                models.Q(away_team=team_filter)
            )

        matches = matches_qs.all()

        # Build matches list
        matches_data = []
        for m in matches:
            matches_data.append({
                "match_id": m.id,
                "home_team": {
                    "id": m.home_team.id if m.home_team else None,
                    "name": m.home_team.name if m.home_team else None,
                    "logo": m.home_team.logo.url if m.home_team and m.home_team.logo else None,
                },
                "away_team": {
                    "id": m.away_team.id if m.away_team else None,
                    "name": m.away_team.name if m.away_team else None,
                    "logo": m.away_team.logo.url if m.away_team and m.away_team.logo else None,
                },
                "home_score": m.home_score,
                "away_score": m.away_score,
            })

        # Append round block
        response_data["rounds"].append({
            "round_id": r.id,
            "round_number": r.round_number,
            "date": r.date,
            "is_ended": r.is_ended,
            "match_count": matches_qs.count(),
            "matches": matches_data
        })

    return Response(response_data)

from rest_framework_simplejwt.views import TokenObtainPairView
from .authentication import MyTokenObtainPairSerializer

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer

