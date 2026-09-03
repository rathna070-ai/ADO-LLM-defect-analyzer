import pytest
import responses

from ado_defect_analysis.ado_client import AdoClient, AdoClientError
from ado_defect_analysis.config import AdoConfig

_ORG = "myorg"
_PROJECT = "myproj"
_BASE = f"https://dev.azure.com/{_ORG}/{_PROJECT}/_apis"


def _config(**overrides) -> AdoConfig:
    return AdoConfig(organization=_ORG, project=_PROJECT, pat="fake-pat", **overrides)


@responses.activate
def test_fetch_closed_defects_maps_tags_without_fetching_comments():
    responses.add(
        responses.POST,
        f"{_BASE}/wit/wiql",
        json={"workItems": [{"id": 1}]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        json={
            "value": [
                {
                    "id": 1,
                    "fields": {
                        "System.Title": "Bug",
                        "System.Tags": "regression; payments",
                        "System.IterationPath": "App\\Sprint 12",
                    },
                }
            ]
        },
        status=200,
    )

    client = AdoClient(_config())
    defects = client.fetch_closed_defects()

    assert len(defects) == 1
    assert defects[0].tags == "regression; payments"
    assert defects[0].comments == ""
    assert defects[0].iteration_path == "App\\Sprint 12"
    # No comments endpoint should have been called since fetch_comments is off by default.
    assert all("/comments" not in call.request.url for call in responses.calls)


@responses.activate
def test_fetch_closed_defects_requests_iteration_path_field():
    responses.add(
        responses.POST,
        f"{_BASE}/wit/wiql",
        json={"workItems": [{"id": 1}]},
        status=200,
    )

    def _capture_fields(request):
        import json

        body = json.loads(request.body)
        assert "System.IterationPath" in body["fields"]
        return (200, {}, json.dumps({"value": []}))

    responses.add_callback(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        callback=_capture_fields,
        content_type="application/json",
    )

    AdoClient(_config()).fetch_closed_defects()


@responses.activate
def test_fetch_closed_defects_pulls_comments_when_enabled():
    responses.add(
        responses.POST,
        f"{_BASE}/wit/wiql",
        json={"workItems": [{"id": 1}]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        json={"value": [{"id": 1, "fields": {"System.Title": "Bug"}}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{_BASE}/wit/workItems/1/comments",
        json={"comments": [{"text": "First comment."}, {"text": "Second comment."}]},
        status=200,
    )

    client = AdoClient(_config(fetch_comments=True))
    defects = client.fetch_closed_defects()

    assert defects[0].comments == "First comment. | Second comment."


@responses.activate
def test_every_request_carries_a_timeout():
    """An unbounded ADO call can hang a scheduled run forever."""
    responses.add(responses.POST, f"{_BASE}/wit/wiql", json={"workItems": [{"id": 1}]}, status=200)
    responses.add(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        json={"value": [{"id": 1, "fields": {"System.Title": "Bug"}}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{_BASE}/wit/workItems/1/comments",
        json={"comments": []},
        status=200,
    )

    AdoClient(_config(fetch_comments=True, request_timeout_seconds=17)).fetch_closed_defects()

    assert responses.calls
    for call in responses.calls:
        assert call.request.req_kwargs["timeout"] == 17


@responses.activate
def test_retries_transient_failure_then_succeeds():
    """A single 429/503 shouldn't lose the run — the session retries it."""
    responses.add(responses.POST, f"{_BASE}/wit/wiql", json={}, status=503)
    responses.add(responses.POST, f"{_BASE}/wit/wiql", json={"workItems": []}, status=200)

    # No exception, and it consumed both queued responses.
    assert AdoClient(_config()).fetch_closed_defects() == []
    assert len(responses.calls) == 2


_QUERY_GUID = "a1b2c3d4-1111-2222-3333-444455556666"


@responses.activate
def test_fetch_defects_for_query_runs_a_saved_query_by_guid():
    responses.add(
        responses.GET,
        f"{_BASE}/wit/wiql/{_QUERY_GUID}",
        json={"workItems": [{"id": 5}]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        json={"value": [{"id": 5, "fields": {"System.Title": "From saved query"}}]},
        status=200,
    )

    defects = AdoClient(_config()).fetch_defects_for_query(_QUERY_GUID)

    assert [d.title for d in defects] == ["From saved query"]


@responses.activate
def test_fetch_defects_for_query_resolves_a_folder_path_first():
    """A path-addressed query needs a lookup before it can be run."""
    responses.add(
        responses.GET,
        f"{_BASE}/wit/queries/Shared%20Queries/Escaped%20Defects",
        json={"id": _QUERY_GUID},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{_BASE}/wit/wiql/{_QUERY_GUID}",
        json={"workItems": [{"id": 7}]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        json={"value": [{"id": 7, "fields": {"System.Title": "Via path"}}]},
        status=200,
    )

    defects = AdoClient(_config()).fetch_defects_for_query("Shared Queries/Escaped Defects")

    assert [d.id for d in defects] == [7]


@responses.activate
def test_fetch_defects_for_query_handles_a_tree_query_result():
    """Tree/one-hop queries return workItemRelations instead of workItems."""
    responses.add(
        responses.GET,
        f"{_BASE}/wit/wiql/{_QUERY_GUID}",
        json={
            "workItemRelations": [
                {"target": {"id": 11}},
                {"target": {"id": 12}},
                {"target": None},
            ]
        },
        status=200,
    )
    responses.add(
        responses.POST,
        f"{_BASE}/wit/workitemsbatch",
        json={"value": [{"id": 11, "fields": {}}, {"id": 12, "fields": {}}]},
        status=200,
    )

    defects = AdoClient(_config()).fetch_defects_for_query(_QUERY_GUID)

    assert sorted(d.id for d in defects) == [11, 12]


@responses.activate
def test_fetch_defects_for_query_returns_empty_for_an_empty_query():
    responses.add(
        responses.GET, f"{_BASE}/wit/wiql/{_QUERY_GUID}", json={"workItems": []}, status=200
    )

    assert AdoClient(_config()).fetch_defects_for_query(_QUERY_GUID) == []


@responses.activate
def test_fetch_defects_for_query_raises_on_a_failed_query():
    responses.add(
        responses.GET, f"{_BASE}/wit/wiql/{_QUERY_GUID}", json={"message": "denied"}, status=403
    )

    with pytest.raises(AdoClientError):
        AdoClient(_config()).fetch_defects_for_query(_QUERY_GUID)


@responses.activate
def test_fetch_closed_defects_returns_empty_when_no_work_items():
    responses.add(
        responses.POST,
        f"{_BASE}/wit/wiql",
        json={"workItems": []},
        status=200,
    )

    client = AdoClient(_config())

    assert client.fetch_closed_defects() == []
