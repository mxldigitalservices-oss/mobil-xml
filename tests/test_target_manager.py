import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from identity.target_manager import TargetManager, TargetCategory, Base


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def test_add_and_filter_by_category(session):
    tm = TargetManager(session)
    await tm.add_target("https://video/x", TargetCategory.VIDEO, "clip")
    await tm.add_target("https://audio/y", TargetCategory.AUDIO_STREAM)
    videos = await tm.get_by_category(TargetCategory.VIDEO)
    audios = await tm.get_by_category(TargetCategory.AUDIO_STREAM)
    assert [t.url for t in videos] == ["https://video/x"]
    assert [t.url for t in audios] == ["https://audio/y"]


async def test_deactivate_removes_from_active_list(session):
    tm = TargetManager(session)
    t = await tm.add_target("https://video/z", TargetCategory.VIDEO)
    assert await tm.deactivate(t.id) is True
    assert await tm.get_by_category(TargetCategory.VIDEO) == []
