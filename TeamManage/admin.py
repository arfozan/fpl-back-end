from django.contrib import admin, messages
from .models import SeasonConfig, Team, Player, Match, Round, TransferHistory, WeeklyBonus, TransferWindow, Bid, TeamSeasonStats, TeamAchievementRank, TeamAchievement
from django import forms
from django.core.exceptions import ValidationError

@admin.register(TransferWindow)
class TransferWindowAdmin(admin.ModelAdmin):
    list_display = ("season", "year", "is_active", "is_contract_open")
    list_filter = ("season", "year", "is_active")
    search_fields = ("season", "year")

    # optional: make is_active toggleable from list view
    list_editable = ("is_active", "is_contract_open")

@admin.register(SeasonConfig)
class SeasonConfigAdmin(admin.ModelAdmin):
    list_display = ("season_name", "current_gameweek", "is_season_active")
    search_fields = ("season_name",)

    def save_model(self, request, obj, form, change):
        # Detect if activation state changed to True
        was_active_before = False
        if change:
            previous = SeasonConfig.objects.get(pk=obj.pk)
            was_active_before = previous.is_season_active

        super().save_model(request, obj, form, change)

        # Only create rounds if this is now active and wasn't active before
        if obj.is_season_active and not was_active_before:
            self.generate_rounds(obj, request)

    def generate_rounds(self, season, request):
        rounds_to_create = []
        for i in range(1, 39):  # 1 to 38
            if not Round.objects.filter(round_number=i, season=season).exists():
                rounds_to_create.append(Round(round_number=i, season=season))

        if rounds_to_create:
            created_rounds = Round.objects.bulk_create(rounds_to_create)

            # Create 5 matches for each round
            matches_to_create = []
            for rnd in created_rounds:
                for _ in range(5):
                    matches_to_create.append(Match(round=rnd))
            Match.objects.bulk_create(matches_to_create)

            self.message_user(request, f"✅ Created {len(created_rounds)} rounds with {len(matches_to_create)} matches.")

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    search_fields = ("name", "manager_name")
    list_display = ("name", "manager_name", "current_balance", "weekly_wage_total", "forecast_end_balance")

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    search_fields = ('first_name', 'last_name')
    list_display = ("first_name", "last_name", "position", "team", "weekly_wage")
    readonly_fields = (
        'first_name',
        'last_name',
        'position',
        'total_base_price',
        'weekly_wage',
        'full_season_wage',         
        'loan_from_team',   
        'is_locked',
        'was_locked',
        'is_transfer_lock',
        'was_academy_player',
        'contract_renew_bonus',
        # 'contract_expiry',
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.GET.get('action') == 'end_loan':
            return qs.filter(is_loan=True)
        return qs
    
def update_season_stats(round_obj):
    for match in round_obj.matches.all():
        if not all([match.home_team, match.away_team, match.home_score, match.away_score]):
            continue  # skip incomplete matches

        # Home stats
        home_stats, _ = TeamSeasonStats.objects.get_or_create(
            team=match.home_team, season=round_obj.season
        )
        # Away stats
        away_stats, _ = TeamSeasonStats.objects.get_or_create(
            team=match.away_team, season=round_obj.season
        )

        if match.home_score > match.away_score:  # Home win
            home_stats.wins += 1
            away_stats.losses += 1
        elif match.home_score < match.away_score:  # Away win
            away_stats.wins += 1
            home_stats.losses += 1
        else:  # Draw
            home_stats.draws += 1
            away_stats.draws += 1

        home_stats.save()
        away_stats.save()

class MatchInline(admin.TabularInline):
    model = Match
    extra = 0  # no extra empty rows, since we already create 5
    fields = ("home_team", "away_team", "home_score", "away_score")
    show_change_link = True

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("season", "round_number", "date", "is_ended")
    list_filter = ("season", "is_ended")
    inlines = [MatchInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)

        obj = form.instance
        if obj.is_ended:
            for match in obj.matches.all():
                if not match.home_team or not match.away_team:
                    raise ValidationError("All matches must have home and away teams before ending the round.")
                if match.home_score is None or match.away_score is None:
                    raise ValidationError("All matches must have scores before ending the round.")

            # if passes, update stats
            update_season_stats(obj)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("get_round_number", "home_team", "away_team", "home_score", "away_score")
    list_filter = ("round__season", "round__round_number")
    search_fields = ("home_team__name", "away_team__name")

    def get_round_number(self, obj):
        return obj.round.round_number
    get_round_number.short_description = "Round"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "round":
            active_season = SeasonConfig.get_active_season()
            if active_season:
                kwargs["queryset"] = Round.objects.filter(season=active_season).order_by("round_number")
            else:
                # If no active season, show no rounds or all rounds depending on your preference
                kwargs["queryset"] = Round.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Update overall stats for both teams
        obj.home_team.update_stats()
        obj.away_team.update_stats()

        # Update season stats for both teams
        season = obj.round.season
        for team in [obj.home_team, obj.away_team]:
            team_season_stats, _ = TeamSeasonStats.objects.get_or_create(
                team=team, season=season
            )
            team_season_stats.update_stats()

@admin.register(TransferHistory)
class TransferHistoryAdmin(admin.ModelAdmin):
    list_display = (
        'player', 'from_team', 'to_team', 'amount',
        'transfer_date', 'is_loan', 'loan_gameweek', 'loan_end_flag'
    )
    # readonly_fields = [f.name for f in TransferHistory._meta.fields]

    def loan_end_flag(self, obj):
        return "✅" if obj.is_loan_end else ""
    loan_end_flag.short_description = "Loan End"

@admin.register(WeeklyBonus)
class WeeklyBonusAdmin(admin.ModelAdmin):
    list_display = ("season", "gameweek", "created_at")
    filter_horizontal = (
        "highest_point_teams",
        "highest_point_players",
        "highest_gk_players",
        "highest_df_players",
        "highest_mf_players",
        "highest_fw_players",
        "special_bonus_players",
    )

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "highest_gk_players":
            kwargs["queryset"] = Player.objects.filter(position="GK")
        elif db_field.name == "highest_df_players":
            kwargs["queryset"] = Player.objects.filter(position="DF")
        elif db_field.name == "highest_mf_players":
            kwargs["queryset"] = Player.objects.filter(position="MF")
        elif db_field.name == "highest_fw_players":
            kwargs["queryset"] = Player.objects.filter(position="FW")
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # validate M2M once and apply bonuses only once
        form.instance.validate_m2m()
        form.instance.apply_bonuses()

class TeamAchievementRankInline(admin.TabularInline):  # or StackedInline
    model = TeamAchievementRank
    extra = 1  # show 1 empty row by default
    autocomplete_fields = ["season"]  # nice dropdown for seasons


@admin.register(TeamAchievement)
class TeamAchievementAdmin(admin.ModelAdmin):
    list_display = ("team", "league_champion", "ucl_champion", "created_at")
    search_fields = ("team__name", "league_champion", "ucl_champion")
    inlines = [TeamAchievementRankInline]

