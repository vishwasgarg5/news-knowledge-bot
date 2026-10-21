from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.research import verify_article


def published(hours_ago: float = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def story(headline: str, source: str = "Local News", url: str = "https://local.example/story", hours_ago: float = 2):
    return {"headline": headline, "source": source, "url": url, "published": published(hours_ago), "summary": ""}


def article(title: str, source: str, url: str, hours_ago: float = 2, summary: str = ""):
    return {"title": title, "source": source, "url": url, "published": published(hours_ago), "summary": summary}


def test_two_independent_publishers_support_multi_source_tier():
    headline = "Government approves new flood barrier after severe river flooding"
    result = verify_article(story(headline), [
        article(headline, "Reuters", "https://www.reuters.com/world/flood"),
        article("Government approves flood barrier after severe river flooding", "Associated Press", "https://apnews.com/article/flood"),
    ])
    assert result["independent_sources"] == 2
    assert result["verification"] == "multi-source"


def test_same_publisher_aliases_and_urls_count_once():
    headline = "Government approves new flood barrier after severe river flooding"
    result = verify_article(story(headline), [
        article(headline, "Reuters", "https://www.reuters.com/world/flood-a"),
        article(headline, "Reuters.com", "https://www.reuters.com/world/flood-b"),
    ])
    assert result["independent_sources"] == 1
    assert result["verification"] == "multi-report"


def test_near_identical_syndicated_copy_does_not_inflate_independence():
    headline = "City approves new bridge after severe flood damage across northern region"
    copied_summary = (
        "City officials approved the new bridge after severe flood damage across the northern region. "
        "Construction plans are expected next week, according to the city administration."
    )
    result = verify_article(story(headline), [
        article(headline, "Publisher A", "https://publisher-a.example/bridge", summary=copied_summary),
        article(headline, "Publisher B", "https://publisher-b.example/bridge", summary=copied_summary),
    ])
    assert result["independent_sources"] == 1
    assert result["duplicate_reporting_copies_excluded"] == 1


def test_stale_and_roundup_evidence_do_not_count():
    headline = "Government approves new flood barrier after severe river flooding"
    result = verify_article(story(headline), [
        article(headline, "Reuters", "https://www.reuters.com/world/old", hours_ago=120),
        article("Government approves new flood barrier after severe river flooding", "Daily News Roundup", "https://digest.example/roundup"),
    ])
    assert result["independent_sources"] == 0
    assert result["verification"] == "single-source"


def test_official_primary_source_keeps_official_tier_without_corrobation():
    headline = "Ministry announces revised national flood warning system"
    result = verify_article(story(headline, "PIB", "https://pib.gov.in/example"), [])
    assert result["official_source"] is True
    assert result["verification"] == "official-source"


def test_unrelated_story_sharing_broad_topic_does_not_count():
    headline = "Central bank raises benchmark interest rate after inflation accelerates"
    result = verify_article(story(headline), [
        article("Technology company raises quarterly revenue forecast after demand accelerates", "Reuters", "https://www.reuters.com/technology/revenue"),
        article("Central bank publishes annual financial stability report", "Associated Press", "https://apnews.com/article/stability"),
    ])
    assert result["independent_sources"] == 0
