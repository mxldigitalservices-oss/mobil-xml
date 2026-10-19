from __future__ import annotations
import enum
from sqlalchemy import String, Enum, select, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession


class Base(DeclarativeBase):
    pass


class TargetCategory(str, enum.Enum):
    VIDEO = "VIDEO"
    AUDIO_STREAM = "AUDIO_STREAM"
    SOCIAL_PROFILE = "SOCIAL_PROFILE"
    PLAYLIST = "PLAYLIST"


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    category: Mapped[TargetCategory] = mapped_column(Enum(TargetCategory), index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TargetManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def init_schema(self) -> None:
        async with self.session.bind.begin() as conn:  # type: ignore[union-attr]
            await conn.run_sync(Base.metadata.create_all)

    async def add_target(
        self, url: str, category: TargetCategory, label: str | None = None
    ) -> Target:
        target = Target(url=url, category=category, label=label)
        self.session.add(target)
        await self.session.commit()
        await self.session.refresh(target)
        return target

    async def get_by_category(self, category: TargetCategory) -> list[Target]:
        result = await self.session.execute(
            select(Target).where(Target.category == category, Target.active.is_(True))
        )
        return list(result.scalars().all())

    async def deactivate(self, target_id: int) -> bool:
        target = await self.session.get(Target, target_id)
        if not target:
            return False
        target.active = False
        await self.session.commit()
        return True
