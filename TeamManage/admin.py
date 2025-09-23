from django.contrib import admin, messages
from .models import SeasonConfig, Team, Player, Match, Round, TransferHistory, WeeklyBonus, TransferWindow, Bid, TeamSeasonStats
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from decimal import Decimal
from datetime import timedelta

@admin.register(TransferWindow)
class TransferWindowAdmin(admin.ModelAdmin):
    list_display = ("season", "year", "is_active", "is_contract_open")
    list_filter = ("season", "year", "is_active")
    search_fields = ("season", "year")

    # optional: make is_active toggleable from list view
    list_editable = ("is_active", "is_contract_open")

@admin.action(description="Advance to next game week (Active Season Only)")
def advance_gameweek(modeladmin, request, queryset):
    active_season = SeasonConfig.get_active_season()

    if not active_season:
        messages.error(request, "❌ No active season found. Please activate a season first.")
        return

    if active_season not in queryset:
        messages.error(request, f"❌ You can only advance the active season ({active_season.season_name}).")
        return

    if active_season.current_gameweek >= 38: #using 7 GW as test case
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

    # Step 1: annotate teams with number of players who have no contract_expiry
    teams_with_counts = Team.objects.annotate(
        no_contract_count=Count('players', filter=Q(players__contract_expiry__isnull=True))
    )

    # We’ll compute penalty manually to check transfer times
    updates = []
    ten_minutes_ago = timezone.now() - timedelta(minutes=10)

    for team in teams_with_counts:
        penalty_count = 0

        # Step 2: get all players in this team with no contract_expiry
        players_no_contract = team.players.filter(contract_expiry__isnull=True)

        for player in players_no_contract:
            # Step 3: find latest transfer to this team
            last_transfer = (
                TransferHistory.objects
                .filter(player=player, to_team=team)
                .order_by('-transfer_date')
                .first()
            )

            if last_transfer:
                # check if transfer is older than 10 minutes
                if last_transfer.transfer_date <= ten_minutes_ago:
                    penalty_count += 1
            else:
                # player might have been originally assigned with no transfer history
                penalty_count += 1

        # Step 4: apply penalty
        penalty = Decimal('5') * penalty_count
        new_balance = (team.current_balance or Decimal('0')) - team.weekly_wage_total - penalty
        team.current_balance = new_balance
        updates.append(team)

    Team.objects.bulk_update(updates, ['current_balance'])

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

@admin.action(description="End Loan and Return Player to Original Club")
def end_loan(modeladmin, request, queryset):
    # queryset here is TransferHistory queryset
    loaned_histories = queryset.filter(is_loan=True, is_loan_end=False).select_related('player')
    active_season = SeasonConfig.objects.filter(is_season_active=True).first()

    if not loaned_histories.exists():
        messages.warning(request, "No active loan histories selected.")
        return

    for history in loaned_histories:
        player = history.player
        if not history.from_team:
            messages.warning(request, f"{player.full_name} has no original club recorded.")
            continue

        with transaction.atomic():
            old_team = history.from_team
            current_team = history.to_team

            player.is_academy_player = player.was_academy_player
            player.was_academy_player = False
            player.is_locked = player.was_locked
            player.was_locked = False

            # Assign back to original team
            player.team = old_team
            player.is_loan = False
            player.loan_from_team = None
            player.save()

            # Mark the transfer history as loan-ended
            history.is_loan_end = True
            history.save()

            # Optionally create a new transfer history for return
            TransferHistory.objects.create(
                season=active_season,
                player=player,
                from_team=current_team,
                to_team=old_team,
                amount=0,
                is_loan_end=True,
            )
    messages.success(request, f"Loan ended for {loaned_histories.count()} players.")

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    search_fields = ('first_name', 'last_name')
    list_display = ("first_name", "last_name", "position", "team", "weekly_wage")
    readonly_fields = (
        'first_name',
        'last_name',
        'position',
        'base_price',
        'total_base_price',
        'weekly_wage',
        'full_season_wage',
        'is_loan',         
        'loan_from_team',   
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
    readonly_fields = [f.name for f in TransferHistory._meta.fields]  # all fields readonly
    actions = [end_loan]

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

from .models import TransferRequest
class TransferRequestAdmin(admin.ModelAdmin):
    list_display = ('player', 'from_team', 'to_team', 'amount', 'is_loan', 'status', 'expires_at', 'created_at', 'updated_at')
    list_filter = ('status', 'from_team', 'to_team', 'is_loan')
    search_fields = ('player__name', 'from_team__name', 'to_team__name', 'message')
    ordering = ('-created_at',)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('player', 'from_team', 'to_team')

admin.site.register(TransferRequest, TransferRequestAdmin)

