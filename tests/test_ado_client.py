import responses

from ado_defect_analysis.ado_client import AdoClient
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
def test_fetch_closed_defects_returns_empty_when_no_work_items():
    responses.add(
        responses.POST,
        f"{_BASE}/wit/wiql",
        json={"workItems": []},
        status=200,
    )

    client = AdoClient(_config())

    assert client.fetch_closed_defects() == []
