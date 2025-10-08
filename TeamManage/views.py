from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from .models import (Team, Player, SeasonConfig, TransferHistory,
                     Match, Bid, NewsPost, TeamSeasonStats, TransferWindow, TransferRequest, TeamAchievement, MaintenanceMode, LoanExtensionRequest)
from .serializers import (
    TeamSummarySerializer, PlayerSerializer,
    SeasonConfigSerializer, TransferHistorySerializer,
    MatchSerializer, BidSerializer, TransferWindow, NewsPostSerializer, TeamSeasonStatsSerializer,
    TransferWindowSerializer, TransferRequestSerializer, NewsPostCreateSerializer, ActiveLoanSerializer,
    LoanExtensionRequestSerializer, ActiveLoanWithExtensionSerializer
)
from django.db import models
from django.db.models import Q, Max, Sum
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

class NewsPagination(PageNumberPagination):
    page_size = 10

@api_view(['GET'])
def get_all_teams_summary(request):
    teams = Team.objects.all()
    serializer = TeamSummarySerializer(teams, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
def team_players(request, team_id):
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return Response({"error": "Team not found"}, status=404)

    position_order = {"GK": 1, "DF": 2, "MF": 3, "FW": 4}
    players_qs = Player.objects.filter(team=team)

    total_weekly_wage = sum((p.weekly_wage for p in players_qs), Decimal("0"))

    # ✅ Count academy vs main players (DB aggregation)
    academy_players_count = players_qs.filter(is_academy_player=True).count()
    main_players_count = players_qs.filter(is_academy_player=False).count()

    # ✅ Count loaned-out players separately
    loaned_out_count = Player.objects.filter(
        loan_from_team=team, is_loan=True, is_academy_player=False
    ).count()

    # Include loaned-out players in total main players
    main_players_count += loaned_out_count

    # ✅ Sort players in Python by position priority
    players_sorted = sorted(
        players_qs,
        key=lambda p: position_order.get(p.position, 99)
    )

    serializer = PlayerSerializer(players_sorted, many=True)

    # 🔹 Team Achievements (merge here)
    achievements = TeamAchievement.objects.filter(team=team).prefetch_related("ranks__season")

    achievements_data = []
    for ach in achievements:
        achievements_data.append({
            "league_champion": ach.league_champion,
            "league_runner_up": ach.league_runner_up,
            "ucl_champion": ach.ucl_champion,
            "ucl_runner_up": ach.ucl_runner_up,
            "ranks": [
                {
                    "season": r.season.season_name,
                    "rank": r.rank
                }
                for r in ach.ranks.all()
            ]
        })

    return Response({
        "team_name": team.name,
        "logo": request.build_absolute_uri(team.logo.url) if team.logo else None,
        "manager_name": team.manager_name,
        "manager_photo": request.build_absolute_uri(team.manager_photo.url) if team.logo else None,
        "total_weekly_wage": total_weekly_wage,
        "forecast_end_balance": team.forecast_end_balance,
        "current_balance": team.current_balance,
        "total_players": main_players_count,
        "academy_players": academy_players_count,
        "players": serializer.data,
        "achievements": achievements_data,
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_team(request):
    try:
        team = Team.objects.get(user_name=request.user)
        return Response({
            "id": team.id,
            "username": request.user.username,
            "name": team.name,
            "manager_name": team.manager_name,
            "manager_photo": request.build_absolute_uri(team.manager_photo.url),
            "logo": request.build_absolute_uri(team.logo.url),
            "current_balance": team.current_balance
        })
    except Team.DoesNotExist:
        return Response({"error": "No team found for this user"}, status=404)
    
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

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_team_players(request):
    user = request.user
    team = Team.objects.filter(user_name=user).first()

    if not team:
        return Response({"team": None, "players": [], "expiring_contracts_count": 0}, status=status.HTTP_200_OK)

    # Players currently in team
    players_qs = (
        Player.objects
        .filter(team=team)
        .select_related("team", "loan_from_team", "contract_expiry")
    )

    # Total weekly wage
    total_weekly_wage = sum((p.weekly_wage for p in players_qs), Decimal("0"))
    total_yearly_wage = Decimal(total_weekly_wage * 38)

    # Count academy and main players
    academy_players_count = players_qs.filter(is_academy_player=True).count()
    main_players_count = players_qs.filter(is_academy_player=False).count()

    # Count loaned-out players (they are not in players_qs)
    loaned_out_count = Player.objects.filter(
        loan_from_team=team,
        is_loan=True,
        is_academy_player=False
    ).count()

    # Include them in the main players count
    main_players_count += loaned_out_count

    # Contract expiring count
    expiring_count = players_qs.filter(contract_expiry__isnull=True).count()

    # Sort players by position order
    players_sorted = sorted(
        players_qs,
        key=lambda p: POSITION_ORDER.get(p.position, 99)
    )

    # Serialize players
    players_data = PlayerSerializer(players_sorted, many=True, context={"request": request}).data

    # Serialize team summary
    team_data = TeamSummarySerializer(team, context={"request": request}).data

    return Response({
        "team": team_data,
        "players": players_data,
        "expiring_contracts_count": expiring_count,
        "total_weekly_wage": str(total_weekly_wage),
        "total_yearly_wage": str(total_yearly_wage),
        "academy_players_count": academy_players_count,
        "main_players_count": main_players_count,
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

    try:
        stats = TeamSeasonStats.objects.get(season_id=season_id, team_id=team_id)
        stats_data = TeamSeasonStatsSerializer(stats).data
    except TeamSeasonStats.DoesNotExist:
        stats_data = None

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

# helpers.py (or inside views)
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
        )

        # --- Update player state ---
        if tr.is_loan:
            # Snapshot academy state before moving
            player.was_academy_player = player.is_academy_player
            player.was_locked = player.is_locked
            player.is_loan = True
            player.loan_from_team = from_team
            player.team = to_team
            player.is_academy_player = True
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

        # ensure only original team can approve
        if original_team.user_name != request.user:
            return Response({"error": "Only original team can approve."}, status=status.HTTP_403_FORBIDDEN)

        loan_request.is_approved = True
        loan_request.responded_at = timezone.now()
        loan_request.transfer.loan_gameweek = loan_request.new_loan_gameweek
        loan_request.transfer.save()
        loan_request.save()

        loan_request.delete()

        return Response({"status": "approved", "new_loan_gameweek": loan_request.new_loan_gameweek})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        loan_request = self.get_object()
        original_team = loan_request.transfer.from_team

        if original_team.user_name != request.user:
            return Response({"error": "Only original team can reject."}, status=status.HTTP_403_FORBIDDEN)

        loan_request.is_approved = False
        loan_request.responded_at = timezone.now()
        loan_request.save()
        loan_request.delete()
        return Response({"status": "rejected"})
    
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

        loan_request.delete()
        return Response({"status": "cancelled"}, status=status.HTTP_200_OK)


