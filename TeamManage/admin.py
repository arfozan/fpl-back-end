from django.contrib import admin, messages
from .models import SeasonConfig, Team, Player, Match, Round, TransferHistory, WeeklyBonus, TransferWindow, Bid
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction

@admin.register(TransferWindow)
class TransferWindowAdmin(admin.ModelAdmin):
    list_display = ("season", "year", "is_active")
    list_filter = ("season", "year", "is_active")
    search_fields = ("season", "year")

    # optional: make is_active toggleable from list view
    list_editable = ("is_active",)

@admin.action(description="Advance to next game week (Active Season Only)")
def advance_gameweek(modeladmin, request, queryset):
    active_season = SeasonConfig.get_active_season()

    if not active_season:
        messages.error(request, "❌ No active season found. Please activate a season first.")
        return

    if active_season not in queryset:
        messages.error(request, f"❌ You can only advance the active season ({active_season.season_name}).")
        return

    if active_season.current_gameweek >= 5: #using 7 GW as test case
        # If current gameweek is 7 or more, we assume the season has ended
        # Season has ended → deactivate
        active_season.is_season_active = False
        active_season.save()
        messages.warning(
            request,
            f"⚠ Season {active_season.season_name} has ended at GW38 and is now deactivated. "
            "Please create or activate a new season."
        )
        return

    # Increment gameweek
    active_season.current_gameweek += 1
    active_season.save()

    # Deduct weekly wages for all teams
    for team in Team.objects.all():
        team.current_balance = (team.current_balance or 0) - team.weekly_wage_total
        team.save()

    messages.success(
        request,
        f"✅ Advanced {active_season.season_name} to Gameweek {active_season.current_gameweek}."
    )

@admin.register(SeasonConfig)
class SeasonConfigAdmin(admin.ModelAdmin):
    list_display = ("season_name", "current_gameweek", "is_season_active")
    actions = [advance_gameweek]

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
        existing_rounds = Round.objects.count()
        rounds_to_create = []

        for i in range(1, 39):  # 1 to 38
            if not Round.objects.filter(round_number=i, season=season).exists():
                rounds_to_create.append(Round(round_number=i, season=season))

        if rounds_to_create:
            Round.objects.bulk_create(rounds_to_create)
            self.message_user(request, f"✅ Created {len(rounds_to_create)} rounds for the active season.")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    search_fields = ("name", "manager_name")
    list_display = ("name", "manager_name", "current_balance", "weekly_wage_total", "forecast_end_balance")

@admin.action(description="End Loan and Return Player to Original Club")
def end_loan(modeladmin, request, queryset):
    loaned_players = queryset.filter(is_loan=True)
    active_season = SeasonConfig.objects.filter(is_season_active=True).first()

    if not loaned_players.exists():
        messages.warning(request, "No loaned players selected.")
        return

    for player in loaned_players:
        if not player.loan_from_team:
            messages.warning(request, f"{player.first_name} {player.last_name} has no original club recorded.")
            continue

        with transaction.atomic():
            old_team = player.loan_from_team
            current_team = player.team

            # Assign back to original team
            player.team = old_team
            player.is_loan = False
            player.loan_from_team = None
            player.save()

            # Create transfer history entry
            TransferHistory.objects.create(
                season=active_season,
                player=player,
                from_team=current_team,
                to_team=old_team,
                amount=0,
                is_loan_end=True,
            )

    messages.success(request, f"Loan ended for {loaned_players.count()} players.")

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    search_fields = ('first_name', 'last_name')
    list_display = ("first_name", "last_name", "position", "team", "weekly_wage")
    readonly_fields = (
        'first_name',
        'last_name',
        'position',
        'base_price',
        'bonus_price',
        'weekly_wage',
        'full_season_wage',
        'is_loan',         
        'loan_from_team',   
    )
    actions = [end_loan]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.GET.get('action') == 'end_loan':
            return qs.filter(is_loan=True)
        return qs


# admin.py
@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("round_number", "date", "season")
    list_filter = ("season",)
    ordering = ("season", "round_number")


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


@admin.register(TransferHistory)
class TransferHistoryAdmin(admin.ModelAdmin):
    list_display = ('player', 'from_team', 'to_team', 'amount', 'transfer_date', 'is_loan', 'loan_gameweek', 'loan_end_flag')
    readonly_fields = ('from_team', 'season')
    fields = ('season', 'player', 'to_team', 'amount', 'is_loan', 'loan_gameweek', 'description', 'from_team')
    autocomplete_fields = ['player', 'to_team']

    def loan_end_flag(self, obj):
        return "✅" if obj.is_loan_end else ""
    loan_end_flag.short_description = "Loan End"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'player':
            # Only players that currently belong to a team (non-free agents)
            kwargs["queryset"] = Player.objects.filter(team__isnull=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        active_season = SeasonConfig.objects.filter(is_season_active=True).first()
        if not active_season:
            messages.error(request, "No active season found. Please set an active season in SeasonConfig.")
            return

        obj.season = active_season
        obj.from_team = obj.player.team
        obj.transfer_date = timezone.now().date()

        super().save_model(request, obj, form, change)

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

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # validate M2M once and apply bonuses only once
        form.instance.validate_m2m()
        form.instance.apply_bonuses()

@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("player", "team", "amount", "created_at", "expires_at")
    list_filter = ("team", "player")
    search_fields = ("player__name", "team__name")



