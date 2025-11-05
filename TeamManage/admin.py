from django.contrib import admin, messages
from .models import SeasonConfig, Team, Player, Match, Round, TransferHistory, WeeklyBonus, TransferWindow, TeamSeasonStats, TeamAchievementRank, TeamAchievement, NewsPost
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from decimal import Decimal
from django import forms
from TeamManage.utils import recalculate_season_stats

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

class BalanceAdjustmentForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    ADJUST_TYPE_CHOICES = [
        ('bonus', 'Bonus Income (also updates current balance)'),
        ('balance', 'Current Balance Only'),
    ]
    adjust_type = forms.ChoiceField(choices=ADJUST_TYPE_CHOICES, label="Adjustment Type")
    amount = forms.DecimalField(max_digits=12, decimal_places=2, label="Amount (+/-)")
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), help_text="Optional note")

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "bonus_income", "current_balance")
    actions = ["adjust_balance_or_bonus"]
    # readonly_fields = ["current_balance", "logo", "manager_name", "bonus_income", "manager_photo"]

    def adjust_balance_or_bonus(self, request, queryset):
        """Admin action to adjust team bonus or balance."""
        if "apply" in request.POST:
            form = BalanceAdjustmentForm(request.POST)

            if form.is_valid():
                adjust_type = form.cleaned_data["adjust_type"]
                amount = form.cleaned_data["amount"]
                reason = form.cleaned_data.get("reason", "")
                count = 0

                for team in queryset:
                    # Convert None to 0 for safety
                    team.current_balance = team.current_balance or Decimal("0")
                    team.bonus_income = team.bonus_income or Decimal("0")

                    if adjust_type == "bonus":
                        team.bonus_income += amount
                        team.current_balance += amount
                    elif adjust_type == "balance":
                        team.current_balance += amount

                    team.save()
                    count += 1

                self.message_user(
                    request,
                    f"Successfully adjusted {count} team(s) ({adjust_type} by {amount}).",
                    messages.SUCCESS,
                )
                return redirect(request.get_full_path())

        else:
            form = BalanceAdjustmentForm(
                initial={"_selected_action": request.POST.getlist("_selected_action")}
            )

        return render(
            request,
            "admin/adjust_balance_or_bonus.html",
            {"teams": queryset, "form": form, "title": "Adjust Bonus or Balance"},
        )

    adjust_balance_or_bonus.short_description = "💰 Adjust bonus income or current balance"

    
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

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'team', 'base_price')
    fields = ('first_name', 'last_name', 'club_name', 'position', 'photo', 'contract_expiry', 'team', 'base_price', 'is_academy_player')
    search_fields = ('first_name', 'last_name', 'team__name')
    list_filter = ('team',)


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
            recalculate_season_stats(obj.season)


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

@admin.register(NewsPost)
class NewsPostAdmin(admin.ModelAdmin):
    list_display = ('headline', 'author', 'date_posted')
    search_fields = ('headline', 'content', 'author__username')
    list_filter = ('date_posted',)
    ordering = ('-date_posted',)


