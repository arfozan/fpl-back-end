from rest_framework import serializers
from .models import Team, Player, SeasonConfig, TransferHistory, Match, Bid, TransferWindow, NewsPost, TeamSeasonStats, TransferRequest
from decimal import Decimal
from rest_framework.exceptions import ValidationError

class PlayerSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    photo = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()
    weekly_wage = serializers.SerializerMethodField()
    full_season_wage = serializers.SerializerMethodField()
    transfer_history = serializers.SerializerMethodField()
    contract_expiry = serializers.SerializerMethodField()
    base_price = serializers.SerializerMethodField()
    current_bid = serializers.SerializerMethodField()
    min_bid = serializers.SerializerMethodField()

    class Meta:
        model = Player
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'photo',
            'club_name', 'position', 'team_name', 'base_price',
            'contract_renew_bonus', 'contract_expiry', 'is_academy_player',
            'weekly_wage', 'full_season_wage', 'transfer_history', 'current_bid', 'min_bid'
        ]

    def get_base_price(self, obj):
        return Decimal(obj.base_price or 0)

    def get_weekly_wage(self, obj):
        return Decimal((obj.weekly_wage or 0))
    
    def get_full_season_wage(self, obj):
        return Decimal((obj.weekly_wage or 0) * 38)

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"
    
    def get_team_name(self, obj):
        return obj.team.name if obj.team else "Free Agent"
    
    def get_photo(self, obj):
        request = self.context.get('request')
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        elif obj.photo:
            return obj.photo.url
        return None
    
    def get_contract_expiry(self, obj):
        if obj.contract_expiry:
            return f"{obj.contract_expiry.season} {obj.contract_expiry.year}"
        return None

    def get_transfer_history(self, obj):
        transfers = TransferHistory.objects.filter(player=obj).select_related("from_team", "to_team", "season").order_by('-transfer_date')
        return TransferHistorySerializer(transfers, many=True, context=self.context).data
    
    def get_current_bid(self, obj):
        # highest bid so far
        bid = Bid.objects.filter(player=obj).order_by('-amount').first()
        return bid.amount if bid else None

    def get_min_bid(self, obj):
        existing_bid = Bid.objects.filter(player=obj).order_by('-amount').first()

        if not existing_bid:
            # No bid yet
            active_window = TransferWindow.objects.filter(is_active=True).first()
            if active_window and obj.contract_expiry_id == active_window.id:
                return Decimal("0")  # free transfer for first bid
            return obj.base_price
        else:
            # Next bid must be +0.1
            return existing_bid.amount + Decimal("0.1")

class TeamSummarySerializer(serializers.ModelSerializer):
    current_balance = serializers.SerializerMethodField()
    forecast_end_balance = serializers.SerializerMethodField()
    class Meta:
        model = Team
        fields = ['id', 'name', 'logo', 'manager_name', 'current_balance', 'forecast_end_balance']

    def get_logo(self, obj):
        request = self.context.get('request')
        if obj.logo:
            return request.build_absolute_uri(obj.logo.url)
        return None
    
    def get_current_balance(self, obj):
        return Decimal(obj.current_balance or 0)
    def get_forecast_end_balance(self, obj):
        return Decimal(obj.forecast_end_balance or 0)

class SeasonConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeasonConfig
        fields = ['id', 'season_name','current_gameweek', 'is_season_active']

class TransferWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferWindow
        fields = ["id", "season", "year", "is_active", "is_contract_open"]

class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "total_wins",
            "total_losses",
            "total_draws",
            "win_percentage",
        ]

class TransferHistorySerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source='player.__str__', read_only=True)
    from_team_name = serializers.CharField(source='from_team.name', read_only=True)
    to_team_name = serializers.CharField(source='to_team.name', read_only=True)

    class Meta:
        model = TransferHistory
        fields = [
            'id', 'season', 'player_name', 'from_team_name', 'to_team_name',
            'amount', 'transfer_date', 'is_loan', 'loan_gameweek',
            'is_loan_end', 'description'
        ]
    def get_amount(self, obj):
        return Decimal(obj.amount or 0)

class MatchSerializer(serializers.ModelSerializer):
    home_team_name = serializers.CharField(source="home_team.name", read_only=True)
    away_team_name = serializers.CharField(source="away_team.name", read_only=True)

    class Meta:
        model = Match
        fields = ["id", "round", "home_team", "away_team", "home_score", "away_score", "home_team_name", "away_team_name",]

class TeamSeasonStatsSerializer(serializers.ModelSerializer):
    win_percentage = serializers.ReadOnlyField()

    class Meta:
        model = TeamSeasonStats
        fields = ["team", "wins", "draws", "losses", "win_percentage"]


class BidSerializer(serializers.ModelSerializer):
    player_name = serializers.SerializerMethodField()
    player_photo = serializers.SerializerMethodField()
    team_name = serializers.CharField(source="team.name", read_only=True)
    amount = serializers.SerializerMethodField()

    class Meta:
        model = Bid
        fields = ["id", "player", "player_name", "player_photo", "team_name", "amount", "expires_at"]

    def get_player_name(self, obj):
        return f"{obj.player.first_name} {obj.player.last_name}"
    
    def get_player_photo(self, obj):
        request = self.context.get("request")
        if obj.player.photo:
            photo_url = obj.player.photo.url
            return request.build_absolute_uri(photo_url) if request else photo_url
        return None
    def get_amount(self, obj):
        return Decimal(obj.amount or 0)

class NewsPostSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = NewsPost
        fields = ['id', 'headline', 'content', 'image', 'date_posted', 'author']

class TransferRequestSerializer(serializers.ModelSerializer):
    player_name = serializers.StringRelatedField(source="player", read_only=True)
    to_team_name = serializers.CharField(source="to_team.name", read_only=True)
    from_team_name = serializers.CharField(source="from_team.name", read_only=True)
    message = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )

    class Meta:
        model = TransferRequest
        fields = "__all__"
        read_only_fields = ("created_by", "status", "created_at", "updated_at", "to_team",
            "from_team", "expires_at")
        
    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount should be greater than 0.")
        return value

    def validate(self, attrs):
        if attrs.get("is_loan"):
            loan_gameweek = attrs.get("loan_gameweek")

            if loan_gameweek is None:
                raise serializers.ValidationError({
                    "Error": ["Loan gameweek is required for loan offers."]
                })

            # check 7–38 inclusive
            if not 7 <= loan_gameweek <= 38:
                raise serializers.ValidationError({
                    "loan_gameweek": ["Loan gameweek must be between 7 and 38."]
                })
            season = SeasonConfig.objects.filter(is_season_active=True).first()
            if season and (loan_gameweek - season.current_gameweek) < 7:
                raise serializers.ValidationError({
                    "loan_gameweek": "Loan must be at least 7 gameweeks ahead."
                })
        return attrs