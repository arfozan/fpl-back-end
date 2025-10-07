from django.urls import path
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    SeasonConfigViewSet, ChangePasswordView, update_team_images, get_all_teams_summary, team_players, player_details, PlayerTransferHistoryAPIView,
    TeamTransferHistoryAPIView, players_list, current_status, NewsPostDetailView, NewsPostListCreateView, my_team_players,
    list_transfer_windows, extend_contract, TransferRequestViewSet, get_my_team, release_player, maintenance_status,
    my_loan_players, LoanExtensionRequestViewSet,
)
from . import views

router = DefaultRouter()
router.register(r'seasons', SeasonConfigViewSet)
router.register(r"transfer-requests", TransferRequestViewSet, basename="transferrequest")
router.register(r'loan-extension-requests', LoanExtensionRequestViewSet, basename='loan-extension-requests')

urlpatterns = router.urls + [
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('my-team/', get_my_team, name='get_my_team'),
    path('update-images/', update_team_images),
    path('team-summary/', get_all_teams_summary, name='team-summary'),
    path('team/<int:team_id>/', team_players, name='team-players'),
    path('playerdetails/<int:player_id>/', player_details, name='player-details'),
    path('player/<int:player_id>/transfers/', PlayerTransferHistoryAPIView.as_view(), name='player-transfer-history'),
    path('team/<int:team_id>/transfers/', TeamTransferHistoryAPIView.as_view(), name='team-transfer-history'),
    # path("matches/team/<int:team_id>/", views.team_matches, name="team-matches"),
    path("season-details/", current_status, name="season-details"),
    # path("season/<int:season_id>/team/<int:team_id>/matches/", views.season_matches),
    # path("season/<int:season_id>/team/<int:team_id>/stats/", views.season_stats),
    path("season/<int:season_id>/team/<int:team_id>/details/", views.season_team_details),
    path("players/", players_list, name="players-list"),
    path("free-agents/", views.free_agents, name="free_agents"),
    path("active-bids/", views.active_bids, name="active_bids"),
    path("bids/", views.create_bid, name="create_bid"),
    path('news/', NewsPostListCreateView.as_view(), name='news-list-create'),
    path('news/<int:pk>/', NewsPostDetailView.as_view(), name='news-detail'),
    # path("teams/<int:team_id>/overall-stats/", views.team_overall_stats, name="team-overall-stats"),
    path("my-team-players/", my_team_players, name="my-team"),
    path('players/<int:player_id>/toggle-academy/', views.toggle_academy, name='toggle-academy'),
    path('players/<int:player_id>/extend-contract/', extend_contract, name='extend-contract'),
    path("players/<int:player_id>/release_player/", release_player, name="release-player"),
    path("transfer-windows/", list_transfer_windows, name="transfer-windows"),
    path("players/available/", views.available_players, name="available-players"),
    path("maintenance/", maintenance_status, name="maintenance_status"),
    path("my-loaned-players/", my_loan_players, name="my-loan-players"),

]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)