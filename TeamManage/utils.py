from TeamManage.models import TeamSeasonRanks, Match, SeasonConfig, Team, WeeklyBonus, MonthlyBonus
from django.db import models
from decimal import Decimal
from django.shortcuts import get_object_or_404

def recalculate_season_stats(season):
        # Reset stats for all teams in this season
    TeamSeasonRanks.objects.filter(season=season).update(
        wins=0,
        draws=0,
        losses=0,
        goals_for=0,
        goals_against=0
    )

    # Ensure every team has a row for this season
    for team in Team.objects.all():
        TeamSeasonRanks.objects.get_or_create(team=team, season=season)

    # Get all matches from completed rounds
    all_matches = Match.objects.filter(
        round__season=season,
        round__is_ended=True
    )

    for match in all_matches:
        if (
            match.home_score is not None
            and match.away_score is not None
            and match.home_team
            and match.away_team
        ):

            # Goals For / Against
            TeamSeasonRanks.objects.filter(team=match.home_team, season=season).update(
                goals_for=models.F("goals_for") + match.home_score,
                goals_against=models.F("goals_against") + match.away_score,
            )

            TeamSeasonRanks.objects.filter(team=match.away_team, season=season).update(
                goals_for=models.F("goals_for") + match.away_score,
                goals_against=models.F("goals_against") + match.home_score,
            )

            # Result: Home win
            if match.home_score > match.away_score:
                TeamSeasonRanks.objects.filter(team=match.home_team, season=season).update(
                    wins=models.F("wins") + 1
                )
                TeamSeasonRanks.objects.filter(team=match.away_team, season=season).update(
                    losses=models.F("losses") + 1
                )

            # Result: Away win
            elif match.home_score < match.away_score:
                TeamSeasonRanks.objects.filter(team=match.home_team, season=season).update(
                    losses=models.F("losses") + 1
                )
                TeamSeasonRanks.objects.filter(team=match.away_team, season=season).update(
                    wins=models.F("wins") + 1
                )

            # Result: Draw
            else:
                TeamSeasonRanks.objects.filter(team=match.home_team, season=season).update(
                    draws=models.F("draws") + 1
                )
                TeamSeasonRanks.objects.filter(team=match.away_team, season=season).update(
                    draws=models.F("draws") + 1
                )

def get_team_bonus_summary(season_id=None, team_id=None):
    from collections import OrderedDict
    
    one = Decimal("1.0")
    half = Decimal("0.5")
    third = Decimal("0.3")

    # ✅ Auto-detect active season if not provided
    if season_id is None:
        active_season = SeasonConfig.objects.filter(is_season_active=True).first()
        if not active_season:
            return {}
        season_id = active_season.id

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

    monthly_bonuses = MonthlyBonus.objects.filter(season_id=season_id)

    for mb in monthly_bonuses:
        if mb.team_id:     # 🟢 skip free agents
            totals[mb.team_id] = totals.get(mb.team_id, Decimal("0")) + mb.bonus_amount

    # ✅ Prepare final result with team info
    result = {}
    for tid, val in totals.items():
        team = get_object_or_404(Team, id=tid)
        result[tid] = {
            "team_name": team.name,
            "logo": team.logo.url if team.logo else None,
            "bonus": float(val),
        }

    # ✅ If single team requested
    if team_id:
        tid = int(team_id)
        team = get_object_or_404(Team, id=tid)
        return {
            tid: {
                "team_name": team.name,
                "logo": team.logo.url if team.logo else None,
                "bonus": float(totals.get(tid, 0)),
            }
        }
    # ✅ Sort by bonus (descending)
    sorted_result = OrderedDict(
        sorted(result.items(), key=lambda item: item[1]["bonus"], reverse=True)
    )

    return sorted_result
