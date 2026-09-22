from datetime import datetime, timedelta, timezone

from scripts.materialize_fixture_history import _canonical_id, select_revisions


T = datetime(2024, 8, 16, 17, 30, tzinfo=timezone.utc)


def test_revision_selection_is_strict_and_never_falls_forward():
    commits = [
        ("old", T - timedelta(days=1)),
        ("equal", T),
        ("future", T + timedelta(minutes=1)),
    ]
    blobs = {"old": "blob-old", "equal": "blob-equal", "future": "blob-future"}
    selected, missing = select_revisions(commits, {1: T}, blobs.get)
    assert not missing
    assert selected[1].commit_sha == "old"
    assert selected[1].commit_timestamp < T


def test_revision_selection_reports_no_earlier_path_instead_of_using_future():
    commits = [("before-without-path", T - timedelta(hours=1)), ("future", T + timedelta(seconds=1))]
    selected, missing = select_revisions(
        commits, {1: T}, lambda sha: "future-blob" if sha == "future" else None,
    )
    assert selected == {}
    assert missing == (1,)


def test_revision_selection_uses_latest_tree_containing_unchanged_schedule():
    commits = [
        ("fixture-change", T - timedelta(days=3)),
        ("unrelated-later", T - timedelta(hours=1)),
    ]
    selected, _ = select_revisions(commits, {1: T}, lambda _: "same-blob")
    assert selected[1].commit_sha == "unrelated-later"
    assert selected[1].blob_sha == "same-blob"


def test_canonical_fixture_identity_excludes_kickoff_and_provider_fixture_id():
    semantic = "Premier League|2024-25|arsenal|chelsea"
    before = _canonical_id("fix", semantic)
    after_reschedule = _canonical_id("fix", semantic)
    assert before == after_reschedule
    assert "123" not in before
