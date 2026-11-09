import pytest
from fastapi.testclient import TestClient

from src.main import create_app

TEAM_A = {"X-Team-Id": "team-a", "X-User-Id": "user-1"}
TEAM_B = {"X-Team-Id": "team-b", "X-User-Id": "user-2"}


@pytest.fixture
def client():
    """A test client on top of a fresh empty database."""
    return TestClient(create_app(":memory:"))


def make_note(client, headers=TEAM_A, **fields):
    payload = {"title": "Plan", "body": "Ship it", **fields}
    response = client.post("/notes", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def assert_error(response, status_code, code):
    """Every error must come back in the same shape."""
    assert response.status_code == status_code, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]


# ---- headers ---------------------------------------------------------


def test_health_needs_no_headers(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-User-Id": "user-1"},
        {"X-Team-Id": "team-a"},
        {"X-Team-Id": "   ", "X-User-Id": "user-1"},
    ],
)
def test_missing_or_blank_identity_header_is_400(client, headers):
    response = client.get("/notes", headers=headers)

    assert_error(response, 400, "missing_header")


# ---- create ----------------------------------------------------------


def test_create_returns_201_with_the_full_note(client):
    response = client.post(
        "/notes",
        json={"title": " Plan ", "body": "Ship it", "tags": ["Work", "q4"]},
        headers=TEAM_A,
    )

    assert response.status_code == 201
    note = response.json()
    assert note["title"] == "Plan"
    assert note["tags"] == ["q4", "work"]
    assert note["team_id"] == "team-a"
    assert note["author_id"] == "user-1"
    assert note["id"]
    assert note["created_at"] == note["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "body": "b"},  # empty title (service rule)
        {"title": "t", "body": "  "},  # blank body (service rule)
        {"body": "b"},  # missing title (shape)
        {"title": 123, "body": "b"},  # wrong type (shape)
        {"title": "t", "body": "b", "tags": "work"},  # tags not a list (shape)
        ["not", "an", "object"],  # body is not an object
    ],
)
def test_create_with_bad_input_is_422_not_500(client, payload):
    response = client.post("/notes", json=payload, headers=TEAM_A)

    assert_error(response, 422, "invalid_input")


def test_create_with_malformed_json_is_422(client):
    response = client.post(
        "/notes",
        content="{not json",
        headers={**TEAM_A, "Content-Type": "application/json"},
    )

    assert_error(response, 422, "invalid_input")


# ---- get -------------------------------------------------------------


def test_get_returns_the_note(client):
    created = make_note(client)

    response = client.get(f"/notes/{created['id']}", headers=TEAM_A)

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_note_is_404(client):
    assert_error(client.get("/notes/nope", headers=TEAM_A), 404, "not_found")


def test_get_other_teams_note_is_404(client):
    created = make_note(client, TEAM_A)

    response = client.get(f"/notes/{created['id']}", headers=TEAM_B)

    assert_error(response, 404, "not_found")


# ---- list ------------------------------------------------------------


def test_list_returns_only_own_team_with_total(client):
    make_note(client, TEAM_A, title="A")
    make_note(client, TEAM_B, title="B")

    body = client.get("/notes", headers=TEAM_A).json()

    assert body["total"] == 1
    assert [n["title"] for n in body["items"]] == ["A"]


def test_list_paginates(client):
    for title in ["one", "two", "three"]:
        make_note(client, title=title)

    first = client.get("/notes?limit=2", headers=TEAM_A).json()
    rest = client.get("/notes?limit=2&offset=2", headers=TEAM_A).json()

    assert first["total"] == 3
    assert [n["title"] for n in first["items"]] == ["three", "two"]
    assert [n["title"] for n in rest["items"]] == ["one"]


def test_list_on_an_empty_team_is_an_empty_page(client):
    assert client.get("/notes", headers=TEAM_A).json() == {"items": [], "total": 0}


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_list_with_bad_paging_is_422(client, query):
    response = client.get(f"/notes?{query}", headers=TEAM_A)

    assert_error(response, 422, "invalid_input")


# ---- update ----------------------------------------------------------


def test_patch_changes_only_what_was_sent(client):
    created = make_note(client, tags=["keep"])

    response = client.patch(
        f"/notes/{created['id']}", json={"title": "New"}, headers=TEAM_A
    )

    assert response.status_code == 200
    note = response.json()
    assert note["title"] == "New"
    assert note["body"] == "Ship it"
    assert note["tags"] == ["keep"]
    assert note["updated_at"] >= created["updated_at"]


def test_patch_with_nothing_to_change_is_422(client):
    created = make_note(client)

    response = client.patch(f"/notes/{created['id']}", json={}, headers=TEAM_A)

    assert_error(response, 422, "invalid_input")


def test_patch_other_teams_note_is_404_and_changes_nothing(client):
    created = make_note(client, TEAM_A, title="Mine")

    response = client.patch(
        f"/notes/{created['id']}", json={"title": "Hacked"}, headers=TEAM_B
    )

    assert_error(response, 404, "not_found")
    assert (
        client.get(f"/notes/{created['id']}", headers=TEAM_A).json()["title"] == "Mine"
    )


# ---- delete ----------------------------------------------------------


def test_delete_returns_204_and_the_note_is_gone(client):
    created = make_note(client)

    response = client.delete(f"/notes/{created['id']}", headers=TEAM_A)

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/notes/{created['id']}", headers=TEAM_A).status_code == 404


def test_delete_other_teams_note_is_404_and_keeps_it(client):
    created = make_note(client, TEAM_A)

    response = client.delete(f"/notes/{created['id']}", headers=TEAM_B)

    assert_error(response, 404, "not_found")
    assert client.get(f"/notes/{created['id']}", headers=TEAM_A).status_code == 200


# ---- search and tag filter -------------------------------------------


def test_list_filters_by_q_and_tag_within_the_team(client):
    make_note(client, TEAM_A, title="Budget", body="numbers", tags=["finance"])
    make_note(client, TEAM_A, title="Lunch", body="budget talk", tags=["food"])
    make_note(client, TEAM_B, title="Theirs", body="budget", tags=["finance"])

    by_word = client.get("/notes?q=BUDGET", headers=TEAM_A).json()
    by_tag = client.get("/notes?tag=Finance", headers=TEAM_A).json()
    both = client.get("/notes?q=budget&tag=food", headers=TEAM_A).json()

    assert by_word["total"] == 2
    assert [n["title"] for n in by_tag["items"]] == ["Budget"]
    assert [n["title"] for n in both["items"]] == ["Lunch"]


def test_search_word_that_is_too_long_is_422(client):
    response = client.get(f"/notes?q={'x' * 101}", headers=TEAM_A)

    assert_error(response, 422, "invalid_input")


# ---- edge cases ------------------------------------------------------


def test_client_cannot_choose_team_or_author_through_the_body(client):
    response = client.post(
        "/notes",
        json={"title": "T", "body": "B", "team_id": "team-b", "author_id": "boss"},
        headers=TEAM_A,
    )

    note = response.json()
    assert note["team_id"] == "team-a"
    assert note["author_id"] == "user-1"
    assert client.get("/notes", headers=TEAM_B).json()["total"] == 0


def test_patch_with_null_fields_means_leave_them_alone(client):
    created = make_note(client, tags=["keep"])

    unchanged = client.patch(
        f"/notes/{created['id']}", json={"tags": None, "title": "New"}, headers=TEAM_A
    ).json()
    only_nulls = client.patch(
        f"/notes/{created['id']}", json={"title": None}, headers=TEAM_A
    )

    assert unchanged["tags"] == ["keep"]
    assert unchanged["title"] == "New"
    assert_error(only_nulls, 422, "invalid_input")


def test_deleting_twice_gives_204_then_404(client):
    created = make_note(client)

    first = client.delete(f"/notes/{created['id']}", headers=TEAM_A)
    second = client.delete(f"/notes/{created['id']}", headers=TEAM_A)

    assert first.status_code == 204
    assert_error(second, 404, "not_found")


# ---- characters the database cannot store, and unexpected failures ----


@pytest.mark.parametrize(
    "raw_body",
    [
        rb'{"title": "\ud800", "body": "b"}',
        rb'{"title": "t", "body": "\ud800"}',
        rb'{"title": "t", "body": "b", "tags": ["\ud800"]}',
    ],
)
def test_lone_surrogate_in_json_is_422_not_500(client, raw_body):
    response = client.post(
        "/notes",
        content=raw_body,
        headers={**TEAM_A, "Content-Type": "application/json"},
    )

    assert_error(response, 422, "invalid_input")


def test_unexpected_failure_still_uses_the_error_shape_and_hides_details():
    app = create_app(":memory:")
    client = TestClient(app, raise_server_exceptions=False)

    def explode(*args, **kwargs):
        raise RuntimeError("secret database detail")

    app.state.service.get = explode
    response = client.get("/notes/anything", headers=TEAM_A)

    assert_error(response, 500, "internal_error")
    assert "secret" not in response.text


# ---- the /docs page --------------------------------------------------


def test_docs_page_lists_the_two_identity_headers_on_every_notes_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]

    for path, method in [
        ("/notes", "post"),
        ("/notes", "get"),
        ("/notes/{note_id}", "get"),
        ("/notes/{note_id}", "patch"),
        ("/notes/{note_id}", "delete"),
    ]:
        names = {p["name"] for p in paths[path][method]["parameters"]}
        assert {"x-team-id", "x-user-id"} <= names, (path, method)

    assert "parameters" not in paths["/health"]["get"]


# ---- every error uses the same shape ----------------------------------


def test_unknown_url_and_wrong_method_use_the_error_shape(client):
    assert_error(client.get("/nope", headers=TEAM_A), 404, "not_found")
    assert_error(client.put("/notes", headers=TEAM_A), 405, "method_not_allowed")
    assert_error(client.post("/health"), 405, "method_not_allowed")


def test_validation_messages_name_the_field(client):
    no_body = client.post("/notes", headers=TEAM_A)
    no_title = client.post("/notes", json={"body": "b"}, headers=TEAM_A)
    bad_tag_type = client.post(
        "/notes", json={"title": "t", "body": "b", "tags": [1]}, headers=TEAM_A
    )
    bad_json = client.post(
        "/notes",
        content="{not json",
        headers={**TEAM_A, "Content-Type": "application/json"},
    )

    assert no_body.json()["error"]["message"].startswith("body:")
    assert no_title.json()["error"]["message"].startswith("title:")
    assert bad_tag_type.json()["error"]["message"].startswith("tags:")
    assert bad_json.json()["error"]["message"].startswith("body:")
