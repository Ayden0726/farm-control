from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import AppSetting, User, UserRole
from app.schemas import LoginIn, SetupIn, SetupStatus, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.seed import seed_demo
from app.deps import get_current_user

router = APIRouter(tags=["auth"])


@router.get("/setup/status", response_model=SetupStatus)
async def setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatus:
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    company = await db.get(AppSetting, "company_name")
    return SetupStatus(
        needs_setup=count == 0,
        company_name=(company.value if company else None),
    )


@router.post("/setup", response_model=TokenOut)
async def setup(payload: SetupIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if count:
        raise HTTPException(400, "Setup already completed")
    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.admin,
    )
    db.add(user)
    db.add(AppSetting(key="company_name", value=payload.company_name))
    db.add(AppSetting(key="setup_completed", value=True))
    await db.flush()
    if payload.load_demo:
        await seed_demo(db)
    await db.commit()
    token = create_access_token(user.id, user.role.value)
    return TokenOut(
        access_token=token, role=user.role.value, email=user.email, full_name=user.full_name
    )


@router.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = (
        await db.execute(select(User).where(User.email == payload.email.lower()))
    ).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(401, "Account disabled")
    token = create_access_token(user.id, user.role.value)
    return TokenOut(
        access_token=token, role=user.role.value, email=user.email, full_name=user.full_name
    )


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
