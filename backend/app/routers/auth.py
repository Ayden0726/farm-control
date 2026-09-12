import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.models import AppSetting, User, UserRole
from app.schemas import LoginIn, SetupIn, SetupStatus, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.seed import seed_demo
from app.deps import get_current_user

logger = logging.getLogger("farmos.auth")
router = APIRouter(tags=["auth"])


def _company_name(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


async def _upsert_setting(db: AsyncSession, key: str, value: object) -> None:
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


@router.get("/setup/status", response_model=SetupStatus)
async def setup_status() -> SetupStatus:
    """Never 500 — the first-run wizard keys off this payload."""
    try:
        async with SessionLocal() as db:
            count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
            company = await db.get(AppSetting, "company_name")
            return SetupStatus(
                needs_setup=int(count or 0) == 0,
                company_name=_company_name(company.value if company else None),
            )
    except Exception:
        logger.exception("setup status failed")
        return SetupStatus(needs_setup=True, company_name=None)


@router.post("/setup", response_model=TokenOut)
async def setup(payload: SetupIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    try:
        count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        if count:
            raise HTTPException(400, "Setup already completed — sign in instead.")
        user = User(
            email=payload.email.lower().strip(),
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name.strip() or "Farm Admin",
            role=UserRole.admin,
        )
        db.add(user)
        await _upsert_setting(db, "company_name", payload.company_name.strip() or "Print Farm")
        await _upsert_setting(db, "setup_completed", True)
        await db.flush()
        await db.commit()
        await db.refresh(user)
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Setup already completed — sign in instead.")
    except Exception:
        logger.exception("setup failed")
        await db.rollback()
        raise HTTPException(
            500,
            "Could not create the admin account. In WSL run: docker compose logs backend",
        )
    if payload.load_demo:
        try:
            await seed_demo(db)
            await db.commit()
        except Exception:
            logger.exception("demo seed failed; admin account was still created")
            await db.rollback()
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(user.id, role)
    return TokenOut(access_token=token, role=role, email=user.email, full_name=user.full_name)


@router.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = (
        await db.execute(select(User).where(User.email == payload.email.lower().strip()))
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
