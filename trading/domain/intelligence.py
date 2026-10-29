"""External-context equality used by the mandatory AI revalidation gate."""


def intelligence_context(snapshot):
    """Compare directional macro and news bias supplied to the AI dossier.

    Excludes volatile RSS headline arrays and background cache health advisories
    so that routine background RSS fetches during AI deliberation do not abort
    an approved trade unless the directional bias itself has flipped.
    """
    news = snapshot.get("news", {})
    return (
        snapshot.get("global_cues", {}).get("global_bias"),
        news.get("news_bias"),
    )
