def current_user() -> int:
    """
    Single-profile accessor. Returns the sole profile id (matches UserProfile.id) until
    multi-user/auth lands — at that point this becomes the one place that swaps to a
    real session-derived user id. New analytics/gamification code should call this
    instead of hardcoding profile_id=1.
    """
    return 1
