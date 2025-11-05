from django.core.management.base import BaseCommand
from django.db.models import Q
from TeamManage.models import Team, Round, Match, TeamSeasonRanks, SeasonConfig


class Command(BaseCommand):
    help = "Updating League Table for the active season"

    def recalculate_season_stats(self, season):
        rounds = Round.objects.filter(season=season)
        teams = Team.objects.all()

        for team in teams:
            wins = draws = losses = gf = ga = 0

            matches = Match.objects.filter(
                Q(home_team=team) | Q(away_team=team),
                round__in=rounds
            ).exclude(home_score__isnull=True, away_score__isnull=True)

            for match in matches:
                if match.home_team == team:
                    gf += match.home_score
                    ga += match.away_score
                    if match.home_score > match.away_score:
                        wins += 1
                    elif match.home_score == match.away_score:
                        draws += 1
                    else:
                        losses += 1
                else:
                    gf += match.away_score
                    ga += match.home_score
                    if match.away_score > match.home_score:
                        wins += 1
                    elif match.away_score == match.home_score:
                        draws += 1
                    else:
                        losses += 1

            obj, _ = TeamSeasonRanks.objects.get_or_create(team=team, season=season)
            obj.wins = wins
            obj.draws = draws
            obj.losses = losses
            obj.goals_for = gf
            obj.goals_against = ga
            obj.save()

    def handle(self, *args, **options):
        # Find the active season
        active_season = SeasonConfig.objects.filter(is_season_active=True).first()

        if not active_season:
            self.stdout.write(self.style.ERROR("No active season found!"))
            return

        self.recalculate_season_stats(active_season)
        self.stdout.write(self.style.SUCCESS(
            f"League table updated successfully for season {active_season.season_name}."
        ))
