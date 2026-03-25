from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from app.api.deps import AdminDep, BotKeyDep, DBSession
from app.models import Role, User
from app.schemas import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead)
async def create_user(payload: UserCreate, session: DBSession, _bot_key: BotKeyDep) -> UserRead:
    # Upsert: return existing user if tg_id already exists
    if payload.tg_id is not None:
        existing = await session.exec(select(User).where(User.tg_id == payload.tg_id))
        user = existing.first()
        if user:
            return UserRead.model_validate(user)

    user = User(name=payload.name, contact=payload.contact, tg_id=payload.tg_id, role=Role.user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.get("", response_model=list[UserRead])
async def list_users(
    session: DBSession,
    admin: AdminDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[UserRead]:
    _ = admin
    users = await session.exec(select(User).offset(offset).limit(limit))
    return [UserRead.model_validate(u) for u in users.all()]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, session: DBSession, admin: AdminDep) -> UserRead:
    _ = admin
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserRead.model_validate(user)
