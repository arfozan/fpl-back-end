from rest_framework import serializers
from .models import Team, Player, SeasonConfig, TransferHistory, Match, Bid, TransferWindow, NewsPost, TeamSeasonStats


class PlayerSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    photo = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()
    weekly_wage = serializers.FloatField(read_only=True)
    full_season_wage = serializers.FloatField(read_only=True)
    transfer_history = serializers.SerializerMethodField()
    contract_expiry = serializers.SerializerMethodField()


    class Meta:
        model = Player
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'photo',
            'nationality', 'position', 'team_name', 'base_price',
            'contract_renew_bonus', 'contract_expiry', 'is_academy_player',
            'weekly_wage', 'full_season_wage', 'transfer_history'
        ]

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
        try:
            return obj.Bid.amount
        except Bid.DoesNotExist:
            return None

    def get_current_bid_team(self, obj):
        try:
            return obj.Bid.team
        except Bid.DoesNotExist:
            return None


class TeamSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ['id', 'name', 'logo', 'manager_name', 'current_balance', 'forecast_end_balance',"total_wins",
            "total_losses", "total_draws", "win_percentage"]

    def get_logo(self, obj):
        request = self.context.get('request')
        if obj.logo:
            return request.build_absolute_uri(obj.logo.url)
        return None

class SeasonConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeasonConfig
        fields = ['id', 'season_name','current_gameweek', 'is_season_active']

class TransferWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferWindow
        fields = ["id", "season", "year", "is_active"]

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

class TeamSeasonStatsSerializer(serializers.ModelSerializer):
    season_name = serializers.CharField(source="season.season_name", read_only=True)

    class Meta:
        model = TeamSeasonStats
        fields = [
            "id",
            "team",
            "season",
            "season_name",
            "wins",
            "losses",
            "draws",
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

class MatchSerializer(serializers.ModelSerializer):
    round_number = serializers.IntegerField(source="round.round_number", read_only=True)
    season = serializers.CharField(source="round.season.season_name", read_only=True)
    home_team_name = serializers.CharField(source="home_team.name", read_only=True)
    away_team_name = serializers.CharField(source="away_team.name", read_only=True)

    class Meta:
        model = Match
        fields = [
            "id",
            "season",
            "round_number",
            "home_team", "home_team_name",
            "away_team", "away_team_name",
            "home_score", "away_score",
        ]

class BidSerializer(serializers.ModelSerializer):
    player_name = serializers.SerializerMethodField()
    player_photo = serializers.SerializerMethodField()
    team_name = serializers.CharField(source="team.name", read_only=True)

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

class NewsPostSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = NewsPost
        fields = ['id', 'headline', 'content', 'image', 'date_posted', 'author']




