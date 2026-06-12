from app.models.common import DateTimeModelMixin, IDModelMixin
from app.models.domain.profiles import Profile
from app.models.domain.rwmodel import RWModel


class Comment(IDModelMixin, DateTimeModelMixin, RWModel):
    body: str
    content_status: str = "visible"
    liked: bool = False
    likes_count: int = 0
    author: Profile
