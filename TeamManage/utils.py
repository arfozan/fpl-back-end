def recalculate_season_stats(season):
    from TeamManage.models import TeamSeasonStats, Match
    from django.db import models


    # Reset stats for all teams in this season
    TeamSeasonStats.objects.filter(season=season).update(wins=0, draws=0, losses=0)

    # Rebuild stats from all finished rounds
    all_matches = Match.objects.filter(round__season=season, round__is_ended=True)

    for match in all_matches:
        if (
            match.home_score is not None
            and match.away_score is not None
            and match.home_team
            and match.away_team
        ):
            # Home win
            if match.home_score > match.away_score:
                TeamSeasonStats.objects.filter(team=match.home_team, season=season).update(
                    wins=models.F("wins") + 1
                )
                TeamSeasonStats.objects.filter(team=match.away_team, season=season).update(
                    losses=models.F("losses") + 1
                )

            # Away win
            elif match.home_score < match.away_score:
                TeamSeasonStats.objects.filter(team=match.home_team, season=season).update(
                    losses=models.F("losses") + 1
                )
                TeamSeasonStats.objects.filter(team=match.away_team, season=season).update(
                    wins=models.F("wins") + 1
                )

            # Draw
            else:
                TeamSeasonStats.objects.filter(team=match.home_team, season=season).update(
                    draws=models.F("draws") + 1
                )
                TeamSeasonStats.objects.filter(team=match.away_team, season=season).update(
                    draws=models.F("draws") + 1
                )

from decimal import Decimal
from .models import WeeklyBonus, Team
from django.shortcuts import get_object_or_404

def get_team_bonus_summary(season_id, team_id=None):
    one = Decimal("1.0")
    half = Decimal("0.5")
    third = Decimal("0.3")

    bonuses = WeeklyBonus.objects.filter(season_id=season_id)
    totals = {}

    for bonus in bonuses:
        # +1 for highest point teams
        for team in bonus.highest_point_teams.all():
            totals[team.id] = totals.get(team.id, Decimal("0")) + one

        # player bonuses added to their team
        player_bonuses = [
            (bonus.highest_point_players.all(), one),
            (bonus.highest_gk_players.all(), half),
            (bonus.highest_df_players.all(), half),
            (bonus.highest_mf_players.all(), half),
            (bonus.highest_fw_players.all(), half),
            (bonus.special_bonus_players.all(), third),
        ]
        for qs, val in player_bonuses:
            for player in qs:
                if player.team_id:
                    totals[player.team_id] = totals.get(player.team_id, Decimal("0")) + val

    # Include team names
    result = {}
    for tid, val in totals.items():
        team_name = get_object_or_404(Team, id=tid).name
        result[tid] = {"team_name": team_name, "logo": team.logo.url if team.logo else None, "bonus": float(val)}

    if team_id:
        tid = int(team_id)
        team_name = get_object_or_404(Team, id=tid).name
        return {tid: {"team_name": team_name, "logo": team.logo.url if team.logo else None, "bonus": float(totals.get(tid, 0))}}
    return result
