from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from starlette import status
from starlette.status import HTTP_400_BAD_REQUEST

from app.api.dependencies.authentication import get_current_user_authorizer
from app.api.dependencies.database import get_repository
from app.core.config import get_app_settings
from app.core.settings.app import AppSettings
from app.db.errors import EntityDoesNotExist
from app.db.repositories.governance import GovernanceRepository
from app.db.repositories.users import UsersRepository
from app.models.domain.users import User
from app.models.schemas.governance import UserContentInResponse, UserNotificationsInResponse
from app.models.schemas.users import UserInResponse, UserInUpdate, UserWithToken
from app.resources import strings
from app.services import jwt
from app.services.authentication import check_email_is_taken, check_username_is_taken

router = APIRouter()


@router.get("", response_model=UserInResponse, name="users:get-current-user")
async def retrieve_current_user(
    user: User = Depends(get_current_user_authorizer()),
    settings: AppSettings = Depends(get_app_settings),
) -> UserInResponse:
    token = jwt.create_access_token_for_user(
        user,
        str(settings.secret_key.get_secret_value()),
    )
    return UserInResponse(
        user=UserWithToken(
            username=user.username,
            email=user.email,
            bio=user.bio,
            image=user.image,
            token=token,
        ),
    )


@router.get(
    "/notifications",
    response_model=UserNotificationsInResponse,
    name="users:list-notifications",
)
async def list_current_user_notifications(
    unread_only: bool = Query(False, alias="unreadOnly"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user_authorizer()),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> UserNotificationsInResponse:
    return await governance_repo.get_notifications(
        user=user,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    name="users:mark-notification-read",
    response_class=Response,
)
async def mark_current_user_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user_authorizer()),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> None:
    try:
        await governance_repo.mark_notification_read(
            notification_id=notification_id,
            user=user,
        )
    except EntityDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification does not exist.",
        )


@router.get(
    "/content",
    response_model=UserContentInResponse,
    name="users:get-current-user-content",
)
async def list_current_user_content(
    content_type: str = Query("articles", alias="type"),
    content_status: str = Query("all", alias="status"),
    q: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user_authorizer()),
    governance_repo: GovernanceRepository = Depends(
        get_repository(GovernanceRepository),
    ),
) -> UserContentInResponse:
    return await governance_repo.get_user_content(
        user=user,
        content_type=content_type,
        content_status=content_status,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.put("", response_model=UserInResponse, name="users:update-current-user")
async def update_current_user(
    user_update: UserInUpdate = Body(..., embed=True, alias="user"),
    current_user: User = Depends(get_current_user_authorizer()),
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
    settings: AppSettings = Depends(get_app_settings),
) -> UserInResponse:
    if user_update.username and user_update.username != current_user.username:
        if await check_username_is_taken(users_repo, user_update.username):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=strings.USERNAME_TAKEN,
            )

    if user_update.email and user_update.email != current_user.email:
        if await check_email_is_taken(users_repo, user_update.email):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=strings.EMAIL_TAKEN,
            )

    user = await users_repo.update_user(user=current_user, **user_update.dict())

    token = jwt.create_access_token_for_user(
        user,
        str(settings.secret_key.get_secret_value()),
    )
    return UserInResponse(
        user=UserWithToken(
            username=user.username,
            email=user.email,
            bio=user.bio,
            image=user.image,
            token=token,
        ),
    )
