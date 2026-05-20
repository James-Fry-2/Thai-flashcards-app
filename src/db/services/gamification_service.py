import math
from datetime import date, timedelta
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.gamification import UserProfile, Achievement, UserAchievement


# XP constants
XP_PER_REVIEW = 2
XP_BONUS_GOOD_EASY = 3
XP_SESSION_COMPLETE = 20

# Achievements to check (key → condition description)
ACHIEVEMENT_CONDITIONS = {
    "first_card": "First card reviewed",
    "streak_3": "3-day streak",
    "streak_7": "7-day streak",
    "streak_30": "30-day streak",
    "cards_50": "50 cards reviewed total",
    "cards_100": "100 cards reviewed",
    "cards_500": "500 cards reviewed",
    "level_5": "Reach level 5",
    "level_10": "Reach level 10",
}

SEED_ACHIEVEMENTS = [
    {"key": "first_card", "name": "First Steps", "description": "Review your first card", "xp_reward": 10, "icon": "👶"},
    {"key": "streak_3", "name": "3-Day Streak", "description": "Study 3 days in a row", "xp_reward": 25, "icon": "🔥"},
    {"key": "streak_7", "name": "Week Warrior", "description": "Study 7 days in a row", "xp_reward": 75, "icon": "🔥"},
    {"key": "streak_30", "name": "Month Master", "description": "Study 30 days in a row", "xp_reward": 300, "icon": "🏆"},
    {"key": "cards_50", "name": "Half Century", "description": "Review 50 cards", "xp_reward": 50, "icon": "📚"},
    {"key": "cards_100", "name": "Centurion", "description": "Review 100 cards", "xp_reward": 100, "icon": "💯"},
    {"key": "cards_500", "name": "Word Hoarder", "description": "Review 500 cards", "xp_reward": 500, "icon": "🌟"},
    {"key": "level_5", "name": "Rising Star", "description": "Reach level 5", "xp_reward": 100, "icon": "⭐"},
    {"key": "level_10", "name": "Thai Apprentice", "description": "Reach level 10", "xp_reward": 250, "icon": "🎓"},
]


def xp_to_level(xp: int) -> int:
    return max(1, int(math.sqrt(xp / 100)))


async def get_or_create_profile(db: AsyncSession) -> UserProfile:
    profile = await db.get(UserProfile, 1)
    if not profile:
        profile = UserProfile(id=1)
        db.add(profile)
        await db.flush()
    return profile


async def seed_achievements(db: AsyncSession) -> None:
    for data in SEED_ACHIEVEMENTS:
        existing = await db.get(Achievement, data["key"])
        if not existing:
            db.add(Achievement(**data))
    await db.flush()


async def add_xp(db: AsyncSession, profile: UserProfile, amount: int) -> dict:
    profile.xp += amount
    new_level = xp_to_level(profile.xp)
    leveled_up = new_level > profile.level
    profile.level = new_level
    return {"xp_earned": amount, "total_xp": profile.xp, "level": profile.level, "leveled_up": leveled_up}


async def update_streak(db: AsyncSession, profile: UserProfile) -> dict:
    today = date.today()
    last = profile.streak_last_date

    if last == today:
        return {"streak": profile.streak_current, "xp_earned": 0}

    if last == today - timedelta(days=1):
        profile.streak_current += 1
    else:
        profile.streak_current = 1

    if profile.streak_current > profile.streak_longest:
        profile.streak_longest = profile.streak_current

    profile.streak_last_date = today

    bonus_xp = min(10 * profile.streak_current, 100)
    await add_xp(db, profile, bonus_xp)
    return {"streak": profile.streak_current, "xp_earned": bonus_xp}


async def check_and_award_achievements(
    db: AsyncSession,
    profile: UserProfile,
    total_reviews: int,
) -> List[str]:
    """Check conditions and award any newly-earned achievements. Returns list of newly earned keys."""
    earned = []

    async def award(key: str) -> None:
        existing = await db.get(UserAchievement, key)
        if not existing:
            achievement = await db.get(Achievement, key)
            if achievement:
                ua = UserAchievement(achievement_key=key, profile_id=1)
                db.add(ua)
                await add_xp(db, profile, achievement.xp_reward)
                earned.append(key)

    if total_reviews >= 1:
        await award("first_card")
    if total_reviews >= 50:
        await award("cards_50")
    if total_reviews >= 100:
        await award("cards_100")
    if total_reviews >= 500:
        await award("cards_500")
    if profile.streak_current >= 3:
        await award("streak_3")
    if profile.streak_current >= 7:
        await award("streak_7")
    if profile.streak_current >= 30:
        await award("streak_30")
    if profile.level >= 5:
        await award("level_5")
    if profile.level >= 10:
        await award("level_10")

    await db.flush()
    return earned


async def get_profile_with_achievements(db: AsyncSession) -> dict:
    profile = await get_or_create_profile(db)
    result = await db.execute(
        select(UserAchievement, Achievement)
        .join(Achievement, Achievement.key == UserAchievement.achievement_key)
        .where(UserAchievement.profile_id == 1)
    )
    earned = [
        {
            "key": ua.achievement_key,
            "name": ach.name,
            "description": ach.description,
            "icon": ach.icon,
            "earned_at": ua.earned_at.isoformat(),
        }
        for ua, ach in result.all()
    ]
    return {
        "xp": profile.xp,
        "level": profile.level,
        "xp_next_level": (profile.level + 1) ** 2 * 100,
        "streak_current": profile.streak_current,
        "streak_longest": profile.streak_longest,
        "achievements": earned,
    }
