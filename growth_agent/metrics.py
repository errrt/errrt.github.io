CWS_ACTIVE_USER_DEFINITIONS = {
    "users": {
        "api_metric": "users",
        "label": "Daily active users",
        "description": (
            "Chrome Web Store API v2の1日単位のアクティブユーザー指標です。"
            "総インストールユーザー数でも、公開ストアページの表示人数でもありません。"
        ),
    },
    "users_7d": {
        "api_metric": "users-7d",
        "label": "7-day active users",
        "description": (
            "Chrome Web Store API v2の直近7日間のアクティブユーザー指標です。"
            "総インストールユーザー数でも、公開ストアページの表示人数でもありません。"
        ),
    },
}

CWS_ACTIVE_USER_TERMS = (
    "users",
    "users-7d",
    "active users",
    "アクティブユーザー",
    "ユーザー数",
    "利用者数",
)

CWS_PUBLIC_USER_CLAIMS = (
    "公開ユーザー数",
    "公開利用者数",
    "公開アクティブユーザー数",
)

CWS_PUBLIC_DISPLAY_CONTEXT = (
    "公開表示",
    "公開ストア",
    "公開カウンタ",
    "public listing",
    "publicly displayed",
)

CWS_PUBLIC_USER_NEGATIONS = (
    "ではない",
    "ではありません",
    "ではなく",
    "でない",
    "を示さない",
    "を表さない",
    "を意味しない",
    "とは異なる",
    "存在しない",
    "not a public",
    "is not public",
    "not publicly displayed",
    "does not represent",
)


def period_is_complete(value):
    """Unknown coverage never authorizes a rate or comparison."""
    expected = value.get("expected_days", 0)
    return (
        value.get("state") == "observed"
        and value.get("value") is not None
        and expected > 0
        and value.get("observed_days") == expected
        and all(value.get(key, 0) == 0 for key in ("missing_days", "pending_days", "failed_days"))
    )
