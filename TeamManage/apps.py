from django.apps import AppConfig

class TeamManageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'TeamManage'

    def ready(self):
        import TeamManage.signals
        import TeamManage.receivers 
