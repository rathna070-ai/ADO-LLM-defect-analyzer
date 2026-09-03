import pytest

from ado_defect_analysis.ado_query import AdoQueryUrlError, is_query_guid, parse_query_url

_GUID = "a1b2c3d4-1111-2222-3333-444455556666"


def test_parses_a_modern_query_url():
    ref = parse_query_url(f"https://dev.azure.com/contoso/Web%20Platform/_queries/query/{_GUID}/")

    assert ref.organization == "contoso"
    assert ref.project == "Web Platform"  # percent-decoded
    assert ref.query_id == _GUID
    assert ref.identifier == _GUID


def test_parses_the_query_edit_route():
    ref = parse_query_url(f"https://dev.azure.com/contoso/Web/_queries/query-edit/{_GUID}")

    assert ref.query_id == _GUID


def test_parses_a_legacy_visualstudio_host():
    ref = parse_query_url(f"https://contoso.visualstudio.com/Web/_queries/query/{_GUID}/")

    assert ref.organization == "contoso"
    assert ref.project == "Web"
    assert ref.query_id == _GUID


def test_parses_a_query_addressed_by_folder_path():
    ref = parse_query_url(
        "https://dev.azure.com/contoso/Web/_queries/query/Shared%20Queries/Escaped%20Defects"
    )

    assert ref.query_id is None
    assert ref.query_path == "Shared Queries/Escaped Defects"
    assert ref.identifier == "Shared Queries/Escaped Defects"


def test_honours_an_explicit_path_parameter():
    ref = parse_query_url(
        "https://dev.azure.com/contoso/Web/_queries?path=Shared%20Queries%2FMy%20Bugs&_a=query"
    )

    assert ref.query_path == "Shared Queries/My Bugs"


def test_tolerates_a_url_pasted_without_a_scheme():
    ref = parse_query_url(f"dev.azure.com/contoso/Web/_queries/query/{_GUID}")

    assert ref.organization == "contoso"
    assert ref.query_id == _GUID


def test_accepts_a_trimmed_url_without_the_queries_marker():
    """Someone who pastes just org/project/id still gets what they meant."""
    ref = parse_query_url(f"https://dev.azure.com/contoso/Web/{_GUID}")

    assert ref.organization == "contoso"
    assert ref.project == "Web"
    assert ref.query_id == _GUID


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "https://example.com/contoso/Web/_queries/query/whatever",  # wrong host
        "https://dev.azure.com/contoso",  # no project
        "https://dev.azure.com/contoso/Web",  # no query at all
    ],
)
def test_rejects_unusable_input_with_a_readable_message(bad: str):
    with pytest.raises(AdoQueryUrlError):
        parse_query_url(bad)


def test_is_query_guid_distinguishes_ids_from_paths():
    assert is_query_guid(_GUID)
    assert not is_query_guid("Shared Queries/My Bugs")
    assert not is_query_guid("")
