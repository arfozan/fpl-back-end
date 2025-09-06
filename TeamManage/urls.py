from django.urls import path
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    SeasonConfigViewSet, ChangePasswordView,
    get_my_team, update_team_images, get_all_teams_summary, team_players, player_details, PlayerTransferHistoryAPIView,
    TeamTransferHistoryAPIView, players_list, current_status, NewsPostDetailView, NewsPostListCreateView
)
from . import views

router = DefaultRouter()
router.register(r'seasons', SeasonConfigViewSet)

urlpatterns = router.urls + [
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('my-team/', get_my_team, name='get_my_team'),
    path('update-images/', update_team_images),
    path('team-summary/', get_all_teams_summary, name='team-summary'),
    path('team/<int:team_id>/', team_players, name='team-players'),
    path('playerdetails/<int:player_id>/', player_details, name='player-details'),
    path('player/<int:player_id>/transfers/', PlayerTransferHistoryAPIView.as_view(), name='player-transfer-history'),
    path('team/<int:team_id>/transfers/', TeamTransferHistoryAPIView.as_view(), name='team-transfer-history'),
    path("matches/team/<int:team_id>/", views.team_matches, name="team-matches"),
    path("matches/active/", views.active_season_matches, name="active-season-matches"),
    path("season-details/", current_status, name="season-details"),
    path("players/", players_list, name="players-list"),
    path("free-agents/", views.free_agents, name="free_agents"),
    path("active-bids/", views.active_bids, name="active_bids"),
    path("bids/", views.create_bid, name="create_bid"),
    path('news/', NewsPostListCreateView.as_view(), name='news-list-create'),
    path('news/<int:pk>/', NewsPostDetailView.as_view(), name='news-detail'),

]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)