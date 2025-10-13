from django.db import models, transaction
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.conf import settings
from .signals import weekly_bonus_applied, player_released
from django.db.models import Q, F
from datetime import timedelta

class TransferWindow(models.Model):
    SEASON_CHOICES = [
        ("Summer", "Summer"),
        ("Winter", "Winter"),
    ]

    season = models.CharField(max_length=10, choices=SEASON_CHOICES)
    year = models.PositiveIntegerField()
    is_active = models.BooleanField(default=False)
    is_contract_open = models.BooleanField(default=False)
    free_transfer_deadline = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "year"], name="unique_transfer_window")
        ]
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        """
        When this window is activated:
        1️⃣ Deactivate all other windows.
        2️⃣ Automatically open contracts (is_contract_open=True).
        3️⃣ Free all players whose contract_expiry matches this window.
        4️⃣ Log releases in TransferHistory.
        """
        with transaction.atomic():
            if self.is_active:
                # Deactivate other active windows
                TransferWindow.objects.filter(is_active=True).exclude(id=self.id).update(is_active=False)

                # Always open contracts when active
                self.is_contract_open = True

                # Save first so self.id is available
                super().save(*args, **kwargs)

                # Expired players with a team
                expired_players = list(Player.objects.filter(contract_expiry=self, team__isnull=False))

                # Release them
                Player.objects.filter(contract_expiry=self, team__isnull=False).update(
                    team=None,
                    is_locked=False,
                    was_locked=False,
                    is_transfer_lock=False,
                    contract_renew_bonus=0
                )

                # Log release + fire signals
                active_season = SeasonConfig.get_active_season()
                for p in expired_players:
                    old_team = p.team

                    TransferHistory.objects.create(
                        season=active_season,   # ✅ keep using SeasonConfig
                        player=p,
                        from_team=old_team,
                        to_team=None,
                        amount=0,
                        description=f"{p.first_name} {p.last_name} released after contract expiry"
                    )

                    player_released.send(
                        sender=self.__class__,
                        player=p,
                        team=old_team,
                        contract_expiry=self,
                        user=old_team.user_name
                    )

                from django.core.management import call_command
                try:
                    call_command("unlock_players")
                except Exception as e:
                    print(f"⚠️ Error running post_window_activation: {e}")
                return  # avoid double save
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
    logo = models.ImageField(
        upload_to='team_logos/',
        blank=True,
        null=True,
        default='logo.png'
    )
    manager_name = models.CharField(max_length=100)
    manager_photo = models.ImageField(
        upload_to='manager_photos/',
        blank=True,
        null=True,
        default='default_human.png'
    )
    user_name = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    bonus_income = models.DecimalField(max_digits=6, decimal_places=1, default=0, help_text="Total bonus income earned by the team")

    current_balance = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True, help_text="Running balance updated weekly")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.current_balance is None:
            self.current_balance = Decimal(0)
        super().save(*args, **kwargs)


    @property
    def weekly_wage_total(self)-> Decimal:
        return sum(player.weekly_wage for player in self.players.all())

    @property
    def forecast_end_balance(self)-> Decimal:
        season = SeasonConfig.get_active_season()
        if not season:
            # No active season info; just return current balance
            return self.current_balance or Decimal(0)

        remaining_weeks = 38 - season.current_gameweek
        if remaining_weeks < 0:
            remaining_weeks = 0

        current_balance = self.current_balance if self.current_balance is not None else Decimal(0)
        weekly_wage_total = self.weekly_wage_total if self.weekly_wage_total is not None else Decimal(0)

        forecast = current_balance - (weekly_wage_total * Decimal(remaining_weeks))
        return forecast.quantize(Decimal("0.00000001"))
    
    def update_stats(self):
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

        self.total_wins = wins
        self.total_losses = losses
        self.total_draws = draws
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
    photo = models.ImageField(
        upload_to='player_photos/',
        blank=True,
        null=True,
        default='default_human.png'
    )

    club_name = models.CharField(max_length=100, null=True, blank=True)
    position = models.CharField(max_length=2, choices=POSITIONS)
    points = models.IntegerField(default=0) 
    bonus_earning = models.DecimalField(max_digits=4, decimal_places=1, default=0, help_text="Total bonus earned by the player")
    is_locked = models.BooleanField(default=False)
    was_locked = models.BooleanField(default=False)
    is_transfer_lock = models.BooleanField(default=False)

    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='players'
    )

    base_price = models.DecimalField(max_digits=3, decimal_places=1 , default=0)
    contract_renew_bonus = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    contract_expiry = models.ForeignKey(
        "TransferWindow",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="players_with_contract_expiry",
    )
    is_academy_player = models.BooleanField(default=False)
    was_academy_player = models.BooleanField(default=False)
    is_loan = models.BooleanField(default=False)
    loan_from_team = models.ForeignKey(
        'Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='loaned_players'
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_base_price(self) -> Decimal:
        return (self.base_price or Decimal("0")) + (self.contract_renew_bonus or Decimal("0"))

    @property
    def weekly_wage(self) -> Decimal:
        total = self.total_base_price
        if total == 0:
            return Decimal("0")
        
        factor = Decimal("6000") if self.is_academy_player else Decimal("2000")
        wage = (total ** 3) / factor
        return wage.quantize(Decimal("0.00000001"))

    @property
    def full_season_wage(self) -> Decimal:
        return (self.weekly_wage * Decimal("38")).quantize(Decimal("0.00000001"))

class Round(models.Model):
    season = models.ForeignKey(
        SeasonConfig,
        on_delete=models.CASCADE,
        related_name="rounds",
    )
    round_number = models.PositiveIntegerField()
    date = models.DateField(null=True, blank=True)
    is_ended = models.BooleanField(default=False)  

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
        related_name="home_matches",
        null=True, blank=True
    )
    away_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="away_matches",
        null=True, blank=True
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
    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="season_stats")
    season = models.ForeignKey("SeasonConfig", on_delete=models.CASCADE, related_name="team_stats")

    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    draws = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("team", "season")

    @property
    def total_matches(self):
        return self.wins + self.losses + self.draws

    @property
    def win_percentage(self):
        if self.total_matches == 0:
            return 0
        return round((self.wins / self.total_matches) * 100, 2)

    def __str__(self):
        return f"{self.team} - {self.season.season_name} ({self.wins}W/{self.draws}D/{self.losses}L)"

class TransferHistory(models.Model):
    season = models.ForeignKey('SeasonConfig', on_delete=models.CASCADE)
    player = models.ForeignKey('Player', on_delete=models.CASCADE)
    from_team = models.ForeignKey(
        'Team', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transfers_out", editable=False
    )
    to_team = models.ForeignKey(
        'Team', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transfers_in"
    )
    amount = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    transfer_date = models.DateTimeField(default=timezone.now)
    is_loan = models.BooleanField(default=False)
    loan_gameweek = models.IntegerField(null=True, blank=True)
    is_loan_end = models.BooleanField(default=False, editable=False)
    description = models.TextField(blank=True, null=True)

    def clean(self):
        # Only keep lightweight checks — no side effects
        if self.from_team and self.to_team and self.from_team == self.to_team:
            raise ValidationError("From team and To team cannot be the same.")
        if self.is_loan and not self.loan_gameweek:
            raise ValidationError("Loan gameweek must be specified for loan deals.")

    def save(self, *args, **kwargs):
    # Only set from_team if explicitly missing AND player has a team that's not equal to to_team
        if self.pk is None and self.from_team is None and self.player and self.player.team != self.to_team:
            self.from_team = self.player.team

        # Run validations (lightweight and side-effect free)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} from {self.from_team} to {self.to_team} ({self.amount})"

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
        one = Decimal("1.0")
        half = Decimal("0.5")
        third = Decimal("0.3")
        """Apply bonuses to teams and players."""
        # 1. Highest Point Teams (+1)
        for team in self.highest_point_teams.all():
            team.current_balance = (team.current_balance or Decimal("0")) + one
            team.bonus_income = (team.bonus_income or Decimal("0")) + one
            team.save(update_fields=["current_balance", "bonus_income"])

        # 2. Highest Point Players (+1)
        for player in self.highest_point_players.all():
            player.bonus_earning = (player.bonus_earning or Decimal("0")) + one
            player.save(update_fields=["bonus_earning"])
            if player.team:
                player.team.current_balance = (player.team.current_balance or Decimal("0")) + one
                player.team.bonus_income = (player.team.bonus_income or Decimal("0")) + one
                player.team.save(update_fields=["current_balance", "bonus_income"])

        # 3–6. Position-specific (+0.5)
        pos_bonus = {
            self.highest_gk_players: half,
            self.highest_df_players: half,
            self.highest_mf_players: half,
            self.highest_fw_players: half,
        }
        for qs, amount in pos_bonus.items():
            for player in qs.all():
                player.bonus_earning = (player.bonus_earning or Decimal("0")) + amount
                player.save(update_fields=["bonus_earning"])
                if player.team:
                    player.team.current_balance = (player.team.current_balance or Decimal("0")) + amount
                    player.team.bonus_income = (player.team.bonus_income or Decimal("0")) + amount
                    player.team.save(update_fields=["current_balance", "bonus_income"])

        # 7. Special Bonus Players (+0.3)
        for player in self.special_bonus_players.all():
            player.bonus_earning = (player.bonus_earning or Decimal("0")) + third
            player.save(update_fields=["bonus_earning"])
            if player.team:
                player.team.current_balance = (player.team.current_balance or Decimal("0")) + third
                player.team.bonus_income = (player.team.bonus_income or Decimal("0")) + third
                player.team.save(update_fields=["current_balance", "bonus_income"])

        weekly_bonus_applied.send(
            sender=self.__class__,
            instance=self,
        )

    def save(self, *args, **kwargs):
        """Save season/gameweek."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.season.season_name} - GW{self.gameweek} Weekly Bonus"

class Bid(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="bid")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="bids")
    amount = models.DecimalField(max_digits=5, decimal_places=1)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    processed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            # First bid: set expiry 24h from now
            self.expires_at = timezone.now() + settings.BID_EXPIRY
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} - {self.team} - {self.amount}"

class NewsPost(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='news_posts')
    headline = models.CharField(max_length=255)
    title_image = models.ImageField(upload_to='news_images/', blank=True, null=True)  # 👈 New field
    content = models.TextField()
    date_posted = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.headline} by {self.author.username}"
    
class PostImage(models.Model):  # for multiple images
    post = models.ForeignKey(NewsPost, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='posts/')
    caption = models.CharField(max_length=255, blank=True)

# Personal Deal Model
class TransferRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_ACCEPTED = "ACCEPTED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_EXPIRED = "EXPIRED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transfer_requests_made")
    season = models.ForeignKey(SeasonConfig, on_delete=models.CASCADE, null=True, blank=True)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="transfer_requests")
    from_team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, related_name="transfer_requests_received")
    to_team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name="transfer_requests_sent")
    amount = models.DecimalField(max_digits=10, decimal_places=1, default=Decimal("0"))
    is_loan = models.BooleanField(default=False)
    loan_gameweek = models.IntegerField(null=True, blank=True)
    message = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.from_team and self.to_team and self.from_team == self.to_team:
            raise ValidationError("From team and To team cannot be the same.")
        if self.is_loan and not self.loan_gameweek:
            raise ValidationError("Loan gameweek must be specified for loan deals.")
        if self.amount and self.amount <= 0:
            raise ValidationError("Amount cannot be zero/negative.")
        
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Request {self.pk} {self.player} {self.from_team} -> {self.to_team} ({self.status})"

class TeamAchievement(models.Model):
    team = models.ForeignKey(
        "Team",
        on_delete=models.CASCADE,
        related_name="achievements"
    )

    # League Achievements
    league_champion = models.CharField(max_length=500, blank=True, null=True)
    league_runner_up = models.CharField(max_length=500, blank=True, null=True)

    # UCL Achievements
    ucl_champion = models.CharField(max_length=500, blank=True, null=True)
    ucl_runner_up = models.CharField(max_length=500, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.team.name} Achievements"

class TeamAchievementRank(models.Model):
    achievement = models.ForeignKey(
        TeamAchievement,
        on_delete=models.CASCADE,
        related_name="ranks"
    )
    season = models.ForeignKey(
        SeasonConfig,
        on_delete=models.CASCADE,
        related_name="achievement_ranks"
    )
    rank = models.IntegerField()

    class Meta:
        unique_together = ("achievement", "season")

    def __str__(self):
        return f"{self.achievement.team.name} - {self.season.season_name} (Rank {self.rank})"

class MaintenanceMode(models.Model):
    is_active = models.BooleanField(default=False)
    message = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return "ON" if self.is_active else "OFF"

class LoanExtensionRequest(models.Model):
    transfer = models.ForeignKey('TransferHistory', on_delete=models.CASCADE, related_name="loan_extensions")
    requested_by = models.ForeignKey('Team', on_delete=models.CASCADE, related_name="loan_extension_requests")
    new_loan_gameweek = models.IntegerField()
    is_approved = models.BooleanField(null=True, blank=True)  # None = pending, True = accepted, False = rejected
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if not self.transfer.is_loan:
            raise ValidationError("Loan extension can only be requested for a loan deal.")
        if self.requested_by != self.transfer.to_team:
            raise ValidationError("Only the current loan team can request an extension.")
        if self.new_loan_gameweek <= self.transfer.loan_gameweek:
            raise ValidationError("New loan gameweek must be greater than current loan gameweek.")

    def __str__(self):
        return f"Loan Extension Request for {self.transfer.player} (GW {self.new_loan_gameweek})"
