"""
INC-07 amendment #1 -- canonical request matching. Ambiguous input must fail
closed: canonicalize_request(...) returns None rather than guessing.
"""

from mcma.portal.canonical import canonicalize_request

BASE = dict(
    raw_url="http://127.0.0.1:8080/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
    raw_method="POST",
    raw_content_type="application/x-www-form-urlencoded",
    raw_body="",
)


def test_method_is_normalized_to_uppercase():
    result = canonicalize_request(**{**BASE, "raw_method": "post"})
    assert result is not None
    assert result.method == "POST"


def test_hostname_is_normalized_and_compared_exactly():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is not None
    assert result.host == "127.0.0.1:8080"


def test_userinfo_in_url_is_rejected():
    result = canonicalize_request(
        raw_url="http://user:pass@127.0.0.1:8080/x", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_malformed_port_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:notaport/x", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_empty_hostname_is_rejected():
    result = canonicalize_request(
        raw_url="http:///x", raw_method="GET", raw_content_type=None, raw_body=None
    )
    assert result is None


def test_non_absolute_path_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080relative", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_query_and_fragment_are_not_part_of_the_route():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x?a=1#frag", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is not None
    assert result.path == "/x"
    assert result.query_fields == frozenset({"a"})


def test_trailing_slash_policy_is_consistent():
    with_slash = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x/", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    without_slash = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert with_slash is not None and without_slash is not None
    assert with_slash.path == without_slash.path == "/x"


def test_root_path_trailing_slash_preserved():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is not None
    assert result.path == "/"


def test_duplicate_slashes_are_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080//SinAuto_MCMA//x", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_encoded_slash_in_path_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x%2Fy", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_encoded_dot_traversal_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x/%2e%2e/y", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_literal_dot_dot_traversal_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x/../y", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_backslash_in_path_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x\\y", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_duplicate_query_parameter_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x?a=1&a=2", raw_method="GET",
        raw_content_type=None, raw_body=None,
    )
    assert result is None


def test_get_with_a_body_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="GET",
        raw_content_type="application/x-www-form-urlencoded", raw_body="a=1",
    )
    assert result is None


def test_unsupported_content_type_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type="multipart/form-data; boundary=x", raw_body="whatever",
    )
    assert result is None


def test_content_type_with_charset_parameter_is_normalized():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type="application/json; charset=UTF-8", raw_body='{"a": 1}',
    )
    assert result is not None
    assert result.content_type == "application/json"
    assert result.body_fields == frozenset({"a"})


def test_malformed_json_body_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type="application/json", raw_body="{not json",
    )
    assert result is None


def test_json_body_that_is_not_an_object_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type="application/json", raw_body="[1, 2, 3]",
    )
    assert result is None


def test_duplicate_form_body_field_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type="application/x-www-form-urlencoded", raw_body="a=1&a=2",
    )
    assert result is None


def test_form_encoded_body_field_set_is_exact():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type="application/x-www-form-urlencoded",
        raw_body="IdRubrique=7&MontantHT=1.00",
    )
    assert result is not None
    assert result.body_fields == frozenset({"IdRubrique", "MontantHT"})


def test_body_with_no_declared_content_type_is_rejected():
    result = canonicalize_request(
        raw_url="http://127.0.0.1:8080/x", raw_method="POST",
        raw_content_type=None, raw_body="a=1",
    )
    assert result is None
