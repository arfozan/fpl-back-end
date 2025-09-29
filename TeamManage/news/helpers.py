# TeamManage/news/helpers.py
from django.contrib.auth import get_user_model
from ..models import NewsPost

User = get_user_model()

def create_news_post(headline, content, title_image, author=None):
    """
    Creates a NewsPost entry. Defaults to 'SystemBot' if no author given.
    """
    if author is None:
        User = get_user_model()
        author = User.objects.get(username="FHPL") 
    return NewsPost.objects.create(
        author=author,
        title_image=title_image,
        headline=headline,
        content=content
    )
