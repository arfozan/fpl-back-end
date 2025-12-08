from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from TeamManage.models import Team

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # You can add custom claims if needed
        token['username'] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        user = self.user
        team = Team.objects.filter(user_name=user).first()

        data.update({
            "user_id": user.id,
            "username": user.username,
            "is_manager": team is not None,
            "team_id": team.id if team else None,
            "team_name": team.name if team else None,
        })

        return data
