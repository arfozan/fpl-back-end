from django.apps import AppConfig


class TeammanageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'TeamManage'

    def ready(self):
        import TeamManage.signals
