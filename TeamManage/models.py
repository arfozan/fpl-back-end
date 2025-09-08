from django.db import models
from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

# Validator for "Summer 2026" or "Winter 2028"
window_validator = RegexValidator(
    regex=r'^(Summer|Winter) \d{4}$',
    message='Format must be like: Summer 2026 or Winter 2028'
)

class TransferWindow(models.Model):
    SEASON_CHOICES = [
        ("Summer", "Summer"),
        ("Winter", "Winter"),
    ]

    season = models.CharField(max_length=10, choices=SEASON_CHOICES)
    year = models.PositiveIntegerField()
    is_active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "year"], name="unique_transfer_window")
        ]
        ordering = ["-year", "season"]

    def save(self, *args, **kwargs):
        # If this window is set active, deactivate others
        if self.is_active:
            TransferWindow.objects.filter(is_active=True).exclude(id=self.id).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.season} {self.year}"

class SeasonConfig(models.Model):
    season_name = models.CharField(max_length=20)  # e.g. "2025-26"
    current_gameweek = models.IntegerField(default=0)
    is_season_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.season_name} ({'Active' if self.is_season_active else 'Inactive'})"

    @classmethod
    def get_active_season(cls):
        return cls.objects.filter(is_season_active=True).first()


class Team(models.Model):
    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='team_logos/')
    manager_name = models.CharField(max_length=100)
    manager_photo = models.ImageField(upload_to='manager_photos/')
    user_name = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    bonus_income = models.FloatField(default=0, help_text="Total bonus income earned by the team")

    current_balance = models.FloatField(null=True, blank=True, help_text="Running balance updated weekly")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.current_balance is None:
            self.current_balance = 0  # default initial balance
        super().save(*args, **kwargs)


    @property
    def weekly_wage_total(self):
        return sum(player.weekly_wage for player in self.players.all())

    @property
    def forecast_end_balance(self):
        season = SeasonConfig.get_active_season()
        if not season:
            # No active season info; just return current balance
            return self.current_balance or 0

        remaining_weeks = 38 - season.current_gameweek
        if remaining_weeks < 0:
            remaining_weeks = 0

        current_balance = self.current_balance if self.current_balance is not None else 0

        forecast = current_balance - (self.weekly_wage_total * remaining_weeks)
        return round(forecast, 3)
    
    total_wins = models.PositiveIntegerField(default=0)
    total_losses = models.PositiveIntegerField(default=0)
    total_draws = models.PositiveIntegerField(default=0)
    win_percentage = models.FloatField(default=0.0)

    def update_stats(self):
        """Recalculate overall stats from all matches."""
        from django.db.models import Q, F

        matches = Match.objects.filter(Q(home_team=self) | Q(away_team=self))

        wins = matches.filter(
            (Q(home_team=self) & Q(home_score__gt=F("away_score"))) |
            (Q(away_team=self) & Q(away_score__gt=F("home_score")))
        ).count()

        losses = matches.filter(
            (Q(home_team=self) & Q(home_score__lt=F("away_score"))) |
            (Q(away_team=self) & Q(away_score__lt=F("home_score")))
        ).count()

        draws = matches.filter(home_score=F("away_score")).count()

        total = wins + losses + draws
        win_pct = (wins / total * 100) if total > 0 else 0

        self.total_wins = wins
        self.total_losses = losses
        self.total_draws = draws
        self.win_percentage = round(win_pct, 2)
        self.save(update_fields=["total_wins", "total_losses", "total_draws", "win_percentage"])

class Player(models.Model):
    POSITIONS = [
        ('GK', 'Goalkeeper'),
        ('DF', 'Defender'),
        ('MF', 'Midfielder'),
        ('FW', 'Forward'),
    ]

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    photo = models.ImageField(upload_to='player_photos/')
    club_name = models.CharField(max_length=100, null=True, blank=True)
    nationality = models.CharField(max_length=50, null=True, blank=True)
    position = models.CharField(max_length=2, choices=POSITIONS)
    bonus_earning = models.FloatField(default=0, help_text="Total bonus earned by the player")

    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='players'
    )

    base_price = models.FloatField(default=0)
    contract_renew_bonus = models.FloatField(default=0)
    contract_expiry = models.ForeignKey(
        "TransferWindow",
        on_delete=models.SET_NULL,  # If a transfer window is deleted, keep player but nullify expiry
        blank=True,
        null=True,
        related_name="players_with_contract_expiry",
    )
    is_academy_player = models.BooleanField(default=False)
    is_loan = models.BooleanField(default=False)
    loan_from_team = models.ForeignKey(
        'Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='loaned_players'
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def bonus_price(self):
        return self.base_price + self.contract_renew_bonus

    @property
    def weekly_wage(self):
        if self.base_price == 0:
            return 0
        factor = 6000 if self.is_academy_player else 2000
        return round((self.bonus_price ** 3) / factor, 3)

    @property
    def full_season_wage(self):
        return round(self.weekly_wage * 38, 3)

class Round(models.Model):
    season = models.ForeignKey(
        SeasonConfig,
        on_delete=models.CASCADE,
        related_name="rounds",
    )
    round_number = models.PositiveIntegerField()
    date = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ("season", "round_number")
        ordering = ["season", "round_number"]

    def clean(self):
        active_season = SeasonConfig.get_active_season()
        if not active_season:
            raise ValidationError("No active season found. Please activate a season first.")
        # Ensure unique round per active season
        if Round.objects.exclude(pk=self.pk).filter(
            round_number=self.round_number, season = self.season
        ).exists():
            raise ValidationError(f"Round {self.round_number} already exists in the active season.")

    def __str__(self):
        return f"{self.season.season_name} - GW{self.round_number} ({self.date})"


class Match(models.Model):
    round = models.ForeignKey(
        Round,
        on_delete=models.CASCADE,
        related_name="matches"
    )
    home_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="home_matches"
    )
    away_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="away_matches"
    )
    home_score = models.PositiveIntegerField(null=True, blank=True)
    away_score = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("round", "home_team", "away_team")
        ordering = ["round"]

    def clean(self):
        if self.home_team == self.away_team:
            raise ValidationError("Home and away team cannot be the same.")

        # Limit to 5 matches per round
        if self.round.matches.exclude(pk=self.pk).count() >= 5:
            raise ValidationError(f"Round {self.round.round_number} already has 5 matches.")

    def __str__(self):
        return f"GW{self.round.round_number}: {self.home_team} vs {self.away_team}"
    
class TeamSeasonStats(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="season_stats")
    season = models.ForeignKey(SeasonConfig, on_delete=models.CASCADE)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    draws = models.PositiveIntegerField(default=0)
    win_percentage = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("team", "season")

    def update_stats(self):
        """Recalculate stats for this team in this season."""
        from django.db.models import Q, F

        matches = Match.objects.filter(
            round__season=self.season
        ).filter(
            Q(home_team=self.team) | Q(away_team=self.team)
        )

        wins = matches.filter(
            (Q(home_team=self.team) & Q(home_score__gt=F("away_score"))) |
            (Q(away_team=self.team) & Q(away_score__gt=F("home_score")))
        ).count()

        losses = matches.filter(
            (Q(home_team=self.team) & Q(home_score__lt=F("away_score"))) |
            (Q(away_team=self.team) & Q(away_score__lt=F("home_score")))
        ).count()

        draws = matches.filter(home_score=F("away_score")).count()

        total = wins + losses + draws
        win_pct = (wins / total * 100) if total > 0 else 0

        self.wins = wins
        self.losses = losses
        self.draws = draws
        self.win_percentage = round(win_pct, 2)
        self.save()


class TransferHistory(models.Model):
    season = models.ForeignKey(SeasonConfig, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    from_team = models.ForeignKey(
        'Team', on_delete=models.SET_NULL, null=True, related_name="transfers_out", editable=False
    )
    to_team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, related_name="transfers_in")
    amount = models.FloatField(default=0)
    transfer_date = models.DateField(default=timezone.now)
    is_loan = models.BooleanField(default=False)
    loan_gameweek = models.IntegerField(null=True, blank=True)
    is_loan_end = models.BooleanField(default=False, editable=False)
    description = models.TextField(blank=True, null=True)

    def clean(self):
        # Prevent same team transfer
        if self.from_team and self.to_team and self.from_team == self.to_team:
            raise ValidationError("From team and To team cannot be the same.")

        # Prevent transferring already loaned-out players
        if self.player.is_loan:
            raise ValidationError(f"{self.player} is currently on loan and cannot be transferred.")

        # Loan transfer must have loan_gameweek
        if self.is_loan and not self.loan_gameweek:
            raise ValidationError("Loan gameweek must be specified for loan deals.")

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new and not self.from_team and self.player.team:
            self.from_team = self.player.team

        # Run validations before saving
        self.full_clean()

        super().save(*args, **kwargs)  # Save transfer first

        if is_new:
            if self.is_loan:
                self.player.is_loan = True
                self.player.loan_from_team = self.from_team
                self.player.team = self.to_team
            else:
                self.player.team = self.to_team
                self.player.is_loan = False
                self.player.loan_from_team = None
            self.player.save(update_fields=["team", "is_loan", "loan_from_team"])

            # Update balances
            if self.from_team:
                self.from_team.current_balance += self.amount
                self.from_team.save(update_fields=["current_balance"])
            if self.to_team:
                self.to_team.current_balance -= self.amount
                self.to_team.save(update_fields=["current_balance"])

class WeeklyBonus(models.Model):
    season = models.ForeignKey("SeasonConfig", on_delete=models.CASCADE, editable=False)
    gameweek = models.IntegerField(editable=False)

    # Bonuses
    highest_point_teams = models.ManyToManyField("Team", blank=True, related_name="bonus_highest_point")
    highest_point_players = models.ManyToManyField("Player", blank=True, related_name="bonus_highest_point")
    highest_gk_players = models.ManyToManyField("Player", blank=True, related_name="bonus_highest_gk")
    highest_df_players = models.ManyToManyField("Player", blank=True, related_name="bonus_highest_df")
    highest_mf_players = models.ManyToManyField("Player", blank=True, related_name="bonus_highest_mf")
    highest_fw_players = models.ManyToManyField("Player", blank=True, related_name="bonus_highest_fw")
    special_bonus_players = models.ManyToManyField("Player", blank=True, related_name="bonus_special")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("season", "gameweek")
        ordering = ["-season", "-gameweek"]

    def clean(self):
        """Attach active season & gameweek before save."""
        from .models import SeasonConfig  # avoid circular imports
        active_season = SeasonConfig.get_active_season()
        if not active_season:
            raise ValidationError("No active season found.")
        self.season = active_season
        self.gameweek = active_season.current_gameweek

    def validate_m2m(self):
        """Check duplicates & positional restrictions for M2M fields."""
        all_players = []
        for qs in [
            self.highest_point_players.all(),
            self.highest_gk_players.all(),
            self.highest_df_players.all(),
            self.highest_mf_players.all(),
            self.highest_fw_players.all(),
            self.special_bonus_players.all(),
        ]:
            all_players.extend(qs)

        # Duplicate player check
        duplicates = [p for p in all_players if all_players.count(p) > 1]
        if duplicates:
            raise ValidationError("A player cannot appear in multiple bonus categories for the same week.")

        # Position checks
        for gk in self.highest_gk_players.all():
            if gk.position != "GK":
                raise ValidationError(f"{gk} is not a goalkeeper.")
        for df in self.highest_df_players.all():
            if df.position != "DF":
                raise ValidationError(f"{df} is not a defender.")
        for mf in self.highest_mf_players.all():
            if mf.position != "MF":
                raise ValidationError(f"{mf} is not a midfielder.")
        for fw in self.highest_fw_players.all():
            if fw.position != "FW":
                raise ValidationError(f"{fw} is not a forward.")

    def apply_bonuses(self):
        """Apply bonuses to teams and players."""
        # 1. Highest Point Teams (+1)
        for team in self.highest_point_teams.all():
            team.current_balance = (team.current_balance or 0) + 1
            team.bonus_income += 1
            team.save(update_fields=["current_balance", "bonus_income"])

        # 2. Highest Point Players (+1)
        for player in self.highest_point_players.all():
            player.bonus_earning += 1
            player.save(update_fields=["bonus_earning"])
            if player.team:
                player.team.current_balance = (player.team.current_balance or 0) + 1
                player.team.bonus_income += 1
                player.team.save(update_fields=["current_balance", "bonus_income"])

        # 3–6. Position-specific (+0.5)
        pos_bonus = {
            self.highest_gk_players: 0.5,
            self.highest_df_players: 0.5,
            self.highest_mf_players: 0.5,
            self.highest_fw_players: 0.5,
        }
        for qs, amount in pos_bonus.items():
            for player in qs.all():
                player.bonus_earning += amount
                player.save(update_fields=["bonus_earning"])
                if player.team:
                    player.team.current_balance = (player.team.current_balance or 0) + amount
                    player.team.bonus_income += amount
                    player.team.save(update_fields=["current_balance", "bonus_income"])

        # 7. Special Bonus Players (+0.3)
        for player in self.special_bonus_players.all():
            player.bonus_earning += 0.3
            player.save(update_fields=["bonus_earning"])
            if player.team:
                player.team.current_balance = (player.team.current_balance or 0) + 0.3
                player.team.bonus_income += 0.3
                player.team.save(update_fields=["current_balance", "bonus_income"])

    def save(self, *args, **kwargs):
        """Save season/gameweek."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.season.season_name} - GW{self.gameweek} Weekly Bonus"

class Bid(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="bid")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="bids")
    amount = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            # First bid: set expiry 24h from now
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} - {self.team} - {self.amount}"

class NewsPost(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='news_posts')
    headline = models.CharField(max_length=255)
    content = models.TextField()
    image = models.ImageField(upload_to='news_images/', blank=True, null=True)
    date_posted = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.headline} by {self.author.username}"

