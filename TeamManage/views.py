from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from .models import Team, Player, SeasonConfig, TransferHistory, Match, Bid, NewsPost, TeamSeasonStats
from .serializers import (
    TeamSummarySerializer, PlayerSerializer,
    SeasonConfigSerializer, TransferHistorySerializer,
    MatchSerializer, BidSerializer, TransferWindow, NewsPostSerializer, TeamSeasonStatsSerializer,
    TransferWindowSerializer,
)
from django.db.models import Q, Max
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import generics, permissions, status
from rest_framework.decorators import action
from django.utils import timezone
from datetime import timedelta

@api_view(['GET'])
def get_all_teams_summary(request):
    teams = Team.objects.all()
    serializer = TeamSummarySerializer(teams, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
def team_players(request, team_id):
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return Response({'error': 'Team not found'}, status=404)

    position_order = {'GK': 1, 'DF': 2, 'MF': 3, 'FW': 4}

    players = Player.objects.filter(team=team).order_by(
        *(["position"] if position_order is None else [])
    )

    players = sorted(players, key=lambda p: position_order.get(p.position, 99))

    serializer = PlayerSerializer(players, many=True)
    total_weekly_wage = sum(p.weekly_wage for p in players)
    

    if players:
        main_players_count = sum(
            1 for p in players if not p.is_academy_player
        )

        academy_players_count = sum(
            1 for p in players if p.is_academy_player
        )
    loaned_out_count = Player.objects.filter(loan_from_team=team, is_loan=True, is_academy_player=False).count()
    main_players_count += loaned_out_count

    return Response({
        'team_name': team.name,
        'logo': request.build_absolute_uri(team.logo.url) if team.logo else None,
        'total_weekly_wage': total_weekly_wage,
        'forecast_end_balance': team.forecast_end_balance,
        'current_balance': team.current_balance,
        'total_players': main_players_count,
        'academy_players': academy_players_count,
        'players': serializer.data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_team(request):
    try:
        team = Team.objects.get(user_name=request.user)
        return Response({
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
    queryset = SeasonConfig.objects.all()
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_team_players(request):
    """
    Return the team (if any) for the logged-in user and the players
    whose Player.team points to that team (team__user_name == request.user).
    """
    # optional: get the Team object (could be None)
    team = Team.objects.filter(user_name=request.user).first()

    # direct filtering by the relation: team__user_name=request.user
    players_qs = (
        Player.objects
        .filter(team__user_name=request.user)
        .select_related("team", "loan_from_team", "contract_expiry")  # optimization
        .order_by("position", "last_name")
    )

    players_data = PlayerSerializer(players_qs, many=True, context={"request": request}).data
    team_data = TeamSummarySerializer(team, context={"request": request}).data if team else None

    return Response({"team": team_data, "players": players_data}, status=status.HTTP_200_OK)

@api_view(["GET"])
def list_transfer_windows(request):
    windows = TransferWindow.objects.all().order_by('id')
    serializer = TransferWindowSerializer(windows, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_academy(request, player_id):
    # Check if any TransferWindow is active
    if not TransferWindow.objects.filter(is_active=True).exists():
        return Response(
            {"error": "No active transfer window. Cannot toggle academy."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        player = Player.objects.get(pk=player_id)
    except Player.DoesNotExist:
        return Response({"error": "Player not found"}, status=status.HTTP_404_NOT_FOUND)

    # Prevent toggle if locked
    if player.is_locked:
        return Response(
            {"error": "Player is locked and cannot be toggled"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Toggle academy and lock player
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
    """
    Extend contract for a player to a new TransferWindow.
    Rules:
    - There must be an active TransferWindow
    - The selected transfer_window_id must be exactly 2 greater than current contract_expiry.id
    Body: {"transfer_window_id": 5}
    """
    # 1️⃣ Check if any active transfer window exists
    if not TransferWindow.objects.filter(is_active=True).exists():
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
    current_id = player.contract_expiry.id if player.contract_expiry else 0
    if window.id < current_id + 2:
        return Response(
            {"error": f"Invalid transfer window selected. Must be exactly 2 after current contract ({current_id})."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 5️⃣ Extend contract
    player.contract_expiry = window
    if current_id != 0:
        player.contract_renew_bonus = (player.contract_renew_bonus or 0) + 0.5
    
    player.save(update_fields=["contract_expiry", "contract_renew_bonus"])

    return Response({
        "id": player.id,
        "contract_expiry": str(window)
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


# 2️⃣ Active season matches only
@api_view(['GET'])
def active_season_matches(request):
    active_season = SeasonConfig.get_active_season()
    if not active_season:
        return Response({"error": "No active season found"}, status=status.HTTP_404_NOT_FOUND)

    matches = Match.objects.filter(round__season=active_season).order_by("round__round_number")
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


# ✅ Season-wise stats for a team
@api_view(["GET"])
def team_season_stats(request, team_id):
    stats = TeamSeasonStats.objects.filter(team_id=team_id).select_related("season")
    serializer = TeamSeasonStatsSerializer(stats, many=True)
    return Response(serializer.data)

@api_view(["GET"])
def players_list(request):
    players = Player.objects.all().order_by("last_name")
    serializer = PlayerSerializer(players, many=True)
    return Response(serializer.data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_bid(request):
    player_id = request.data.get("player_id")
    amount = float(request.data.get("amount", 0))

    print("DEBUG: Backend received bid")
    print("DEBUG: Player ID:", player_id)

    user = request.user
    if not user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

    # Get the team from the logged-in user
    try:
        team = Team.objects.get(user_name=user)
        player = Player.objects.get(id=player_id)
        season = SeasonConfig.get_active_season()
    except Team.DoesNotExist:
        return Response({"error": "No team found for this user"}, status=400)
    except Player.DoesNotExist:
        return Response({"error": "Invalid player"}, status=400)

    # --- Free agent check ---
    if player.team:
        return Response(
            {"error": "This player already belongs to a team and cannot be bid on."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # --- Eligibility check ---
    forecast_end_balance = team.forecast_end_balance
    current_gameweek = season.current_gameweek

    # Calculate cost for this new bid
    new_bid_cost = amount + player.weekly_wage * (38 - current_gameweek)

    # Calculate cost of existing active bids by this team
    active_bids = Bid.objects.filter(team=team, player__team__isnull=True)

    active_bids_cost = 0
    for b in active_bids:
        # Important: skip this player if it's already being updated
        if b.player_id == player.id:
            continue
        active_bids_cost += b.amount + b.player.weekly_wage * (38 - current_gameweek)

    total_future_commitment = new_bid_cost + active_bids_cost

    if forecast_end_balance - total_future_commitment <= -15:
        return Response(
            {"error": "Insufficient forecast balance, cannot place bid"},
            status=status.HTTP_400_BAD_REQUEST,
        )


    # --- One bid per player ---
    existing_bid = Bid.objects.filter(player=player).first()

    if existing_bid:
        if amount > existing_bid.amount:
            # Update existing bid (higher bid replaces it)
            existing_bid.team = team
            existing_bid.amount = amount
            existing_bid.expires_at = timezone.now() + timedelta(hours=24)
            existing_bid.save(update_fields=["team", "amount", "expires_at"])
            return Response(
                {"message": "Bid updated successfully", "bid_id": existing_bid.id},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "New bid must be higher than current bid"},
                status=status.HTTP_400_BAD_REQUEST
            )

    # --- First bid for this player ---
    bid = Bid.objects.create(
        team=team,
        player=player,
        amount=amount,
        expires_at=timezone.now() + timedelta(hours=24)
    )

    return Response(
        {
            "message": "Bid placed successfully",
            "bid_id": bid.id,
            "debug_player_id": player.id,
            "debug_team_id": team.id
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
        }

    return Response({
        "season": season_data,
        "transfer_window": transfer_window_data
    })

class NewsPostListCreateView(generics.ListCreateAPIView):
    queryset = NewsPost.objects.all().order_by('-date_posted')
    serializer_class = NewsPostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

class NewsPostDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = NewsPost.objects.all()
    serializer_class = NewsPostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
