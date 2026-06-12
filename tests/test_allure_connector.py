"""Tests for the Allure TestOps connector.

All HTTP traffic is intercepted via httpx.MockTransport — no real instance needed.
Fixtures are loaded from tests/fixtures/*.json.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from testops_mirror.connectors.allure_testops import AllureTestOpsConnector
from testops_mirror.exceptions import AuthError, ConnectorError

# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


AUTH_RESP = _load("auth_response.json")
LIST_RESP = _load("testcase_list.json")
DETAIL_RESP = _load("testcase_detail.json")
STEPS_RESP = _load("testcase_steps.json")

ENDPOINT = "https://testops.example.com"
PROJECT_ID = "99"

# ---------------------------------------------------------------------------
# MockTransport helpers
# ---------------------------------------------------------------------------

Route = Callable[[httpx.Request], httpx.Response]


class MockRouter:
    """Simple request router for httpx.MockTransport."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, str, Route]] = []

    def add(self, method: str, path: str, handler: Route) -> None:
        self._routes.append((method.upper(), path, handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        for method, path, handler in self._routes:
            if request.method == method and request.url.path == path:
                return handler(request)
        return httpx.Response(404, json={"error": f"no route for {request.url.path}"})

    def build_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _json_resp(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _auth_handler(_: httpx.Request) -> httpx.Response:
    return _json_resp(AUTH_RESP)


def _list_handler(_: httpx.Request) -> httpx.Response:
    return _json_resp(LIST_RESP)


def _detail_handler(_: httpx.Request) -> httpx.Response:
    return _json_resp(DETAIL_RESP)


def _steps_handler(_: httpx.Request) -> httpx.Response:
    return _json_resp(STEPS_RESP)


def _make_connector(router: MockRouter) -> AllureTestOpsConnector:
    return AllureTestOpsConnector(
        endpoint=ENDPOINT,
        api_token="test-token",
        http_client=router.build_client(),
    )


def _full_router(
    *,
    detail_id: str = "2301",
    detail_data: Any = None,
    steps_data: Any = None,
    list_data: Any = None,
) -> MockRouter:
    """Build a router that handles the happy-path flow for one test case."""
    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add(
        "GET",
        "/api/rs/testcase",
        _list_handler if list_data is None else lambda _: _json_resp(list_data),
    )
    router.add(
        "GET",
        f"/api/rs/testcase/{detail_id}",
        _detail_handler if detail_data is None else lambda _: _json_resp(detail_data),
    )
    router.add(
        "GET",
        f"/api/rs/testcase/{detail_id}/scenario",
        _steps_handler if steps_data is None else lambda _: _json_resp(steps_data),
    )
    router.add("GET", f"/api/rs/testcase/{detail_id}/step", lambda _: _json_resp([]))
    return router


# ---------------------------------------------------------------------------
# 1. Authentication: token exchange and Bearer header
# ---------------------------------------------------------------------------


def test_auth_exchanges_token() -> None:
    auth_calls: list[httpx.Request] = []

    def capturing_auth(req: httpx.Request) -> httpx.Response:
        auth_calls.append(req)
        return _json_resp(AUTH_RESP)

    router = _full_router()
    router._routes = []  # replace with capturing version
    router.add("POST", "/api/uaa/oauth/token", capturing_auth)
    router.add("GET", "/api/rs/testcase", _list_handler)
    router.add("GET", "/api/rs/testcase/2301", _detail_handler)
    router.add("GET", "/api/rs/testcase/2301/scenario", _steps_handler)
    router.add("GET", "/api/rs/testcase/2301/step", lambda _: _json_resp([]))
    router.add("GET", "/api/rs/testcase/2302", _detail_handler)
    router.add("GET", "/api/rs/testcase/2302/scenario", _steps_handler)
    router.add("GET", "/api/rs/testcase/2302/step", lambda _: _json_resp([]))

    connector = _make_connector(router)
    list(connector.iter_test_cases(PROJECT_ID))

    assert len(auth_calls) == 1
    body = dict(pair.split("=") for pair in auth_calls[0].content.decode().split("&"))
    assert body["grant_type"] == "apitoken"
    assert body["token"] == "test-token"


def test_bearer_sent_in_subsequent_requests() -> None:
    bearer_values: list[str] = []

    def capturing_list(req: httpx.Request) -> httpx.Response:
        bearer_values.append(req.headers.get("authorization", ""))
        return _json_resp({"content": [], "totalPages": 1})

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", capturing_list)

    connector = _make_connector(router)
    list(connector.iter_test_cases(PROJECT_ID))

    assert len(bearer_values) == 1
    assert bearer_values[0] == f"Bearer {AUTH_RESP['access_token']}"


# ---------------------------------------------------------------------------
# 2. Pagination
# ---------------------------------------------------------------------------


def test_pagination_fetches_all_pages() -> None:
    page_0 = {
        "content": [{"id": 1, "name": "Case One"}],
        "totalPages": 2,
        "number": 0,
    }
    page_1 = {
        "content": [{"id": 2, "name": "Case Two"}],
        "totalPages": 2,
        "number": 1,
    }
    call_count = {"n": 0}

    def paged_list(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params.get("page", "0"))
        return _json_resp(page_0 if page == 0 else page_1)

    simple_detail = {
        "id": 0,
        "name": "x",
        "status": "Ready",
        "automated": False,
        "tags": [],
        "customFields": [],
        "links": [],
    }

    def detail_handler(req: httpx.Request) -> httpx.Response:
        case_id = req.url.path.split("/")[-1]
        call_count["n"] += 1
        return _json_resp({**simple_detail, "id": int(case_id), "name": f"Case {case_id}"})

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", paged_list)
    router.add("GET", "/api/rs/testcase/1", detail_handler)
    router.add("GET", "/api/rs/testcase/1/scenario", lambda _: _json_resp([]))
    router.add("GET", "/api/rs/testcase/1/step", lambda _: _json_resp([]))
    router.add("GET", "/api/rs/testcase/2", detail_handler)
    router.add("GET", "/api/rs/testcase/2/scenario", lambda _: _json_resp([]))
    router.add("GET", "/api/rs/testcase/2/step", lambda _: _json_resp([]))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))

    assert len(cases) == 2
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 3. Full case mapping
# ---------------------------------------------------------------------------


def test_full_case_mapping() -> None:
    router = _full_router()
    router.add("GET", "/api/rs/testcase/2302", _detail_handler)
    router.add("GET", "/api/rs/testcase/2302/scenario", _steps_handler)
    router.add("GET", "/api/rs/testcase/2302/step", lambda _: _json_resp([]))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))

    case = next(c for c in cases if c.id == "2301")

    assert case.name == "Transfer to blocked account"
    assert case.status == "Ready"
    assert case.automated is False
    assert "api" in case.tags
    assert "negative" in case.tags
    assert case.suite_path == ("Transfers", "Negative")
    assert case.custom_fields.get("Priority") == ["P1"]
    assert len(case.links) == 1
    assert case.links[0].name == "BAN-17"
    assert case.links[0].type == "issue"
    assert case.source_project == PROJECT_ID
    assert "2301" in (case.source_url or "")


def test_status_as_string_mapped() -> None:
    detail = {**DETAIL_RESP, "status": "Draft"}
    router = _full_router(detail_data=detail)
    router.add("GET", "/api/rs/testcase/2302", lambda _: _json_resp(detail))
    router.add("GET", "/api/rs/testcase/2302/scenario", _steps_handler)
    router.add("GET", "/api/rs/testcase/2302/step", lambda _: _json_resp([]))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))
    case = next(c for c in cases if c.id == "2301")
    assert case.status == "Draft"


def test_steps_mapped_with_nesting() -> None:
    router = _full_router()
    router.add("GET", "/api/rs/testcase/2302", _detail_handler)
    router.add("GET", "/api/rs/testcase/2302/scenario", _steps_handler)
    router.add("GET", "/api/rs/testcase/2302/step", lambda _: _json_resp([]))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))
    case = next(c for c in cases if c.id == "2301")

    assert len(case.steps) == 2
    assert case.steps[0].name == "Send POST /transfers with blocked recipient account ID"
    assert case.steps[0].expected_result == "HTTP 422 Unprocessable Entity"
    assert len(case.steps[1].steps) == 2
    assert case.steps[1].steps[0].name == "Field 'errorCode' equals 'ACCOUNT_BLOCKED'"


# ---------------------------------------------------------------------------
# 4. Step fallback: empty /scenario -> use /step
# ---------------------------------------------------------------------------


def test_step_fallback_to_step_endpoint() -> None:
    fallback_steps = [{"name": "Fallback step", "expectedResult": None, "steps": []}]

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add(
        "GET",
        "/api/rs/testcase",
        lambda _: _json_resp({"content": [{"id": 2301, "name": "x"}], "totalPages": 1}),
    )
    router.add("GET", "/api/rs/testcase/2301", _detail_handler)
    router.add("GET", "/api/rs/testcase/2301/scenario", lambda _: _json_resp([]))  # empty
    router.add("GET", "/api/rs/testcase/2301/step", lambda _: _json_resp(fallback_steps))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))

    assert len(cases) == 1
    assert cases[0].steps[0].name == "Fallback step"


def test_step_fallback_404_on_scenario() -> None:
    fallback_steps = [{"name": "Step via /step endpoint", "expectedResult": None, "steps": []}]

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add(
        "GET",
        "/api/rs/testcase",
        lambda _: _json_resp({"content": [{"id": 2301, "name": "x"}], "totalPages": 1}),
    )
    router.add("GET", "/api/rs/testcase/2301", _detail_handler)
    router.add("GET", "/api/rs/testcase/2301/scenario", lambda _: httpx.Response(404))
    router.add("GET", "/api/rs/testcase/2301/step", lambda _: _json_resp(fallback_steps))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))

    assert cases[0].steps[0].name == "Step via /step endpoint"


# ---------------------------------------------------------------------------
# 5. Retry on 429 with Retry-After
# ---------------------------------------------------------------------------


def test_retry_on_429_respects_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "testops_mirror.connectors.allure_testops.time.sleep", lambda s: sleeps.append(s)
    )

    call_n = {"n": 0}

    def flaky_list(_: httpx.Request) -> httpx.Response:
        call_n["n"] += 1
        if call_n["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return _json_resp({"content": [], "totalPages": 1})

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", flaky_list)

    connector = _make_connector(router)
    list(connector.iter_test_cases(PROJECT_ID))

    assert call_n["n"] == 3
    assert sleeps == [2.0, 2.0]


def test_retry_on_429_raises_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("testops_mirror.connectors.allure_testops.time.sleep", lambda _: None)

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", lambda _: httpx.Response(429, json={}))

    connector = _make_connector(router)
    from testops_mirror.exceptions import RateLimitError

    with pytest.raises(RateLimitError):
        list(connector.iter_test_cases(PROJECT_ID))


# ---------------------------------------------------------------------------
# 6. Retry on 503
# ---------------------------------------------------------------------------


def test_retry_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("testops_mirror.connectors.allure_testops.time.sleep", lambda _: None)

    call_n = {"n": 0}

    def flaky_list(_: httpx.Request) -> httpx.Response:
        call_n["n"] += 1
        if call_n["n"] < 3:
            return httpx.Response(503, json={"error": "service unavailable"})
        return _json_resp({"content": [], "totalPages": 1})

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", flaky_list)

    connector = _make_connector(router)
    list(connector.iter_test_cases(PROJECT_ID))

    assert call_n["n"] == 3


def test_retry_on_503_raises_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("testops_mirror.connectors.allure_testops.time.sleep", lambda _: None)

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", lambda _: httpx.Response(503, json={}))

    connector = _make_connector(router)
    with pytest.raises(ConnectorError):
        list(connector.iter_test_cases(PROJECT_ID))


# ---------------------------------------------------------------------------
# 7. Graceful fallback: one failing case does not abort sync
# ---------------------------------------------------------------------------


def test_graceful_fallback_skips_failing_case() -> None:
    list_data = {
        "content": [
            {"id": 2301, "name": "Transfer to blocked account"},
            {"id": 2302, "name": "Successful transfer"},
        ],
        "totalPages": 1,
    }
    good_detail = {
        "id": 2302,
        "name": "Successful transfer",
        "status": "Ready",
        "automated": False,
        "tags": [],
        "customFields": [],
        "links": [],
    }

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", lambda _: _json_resp(list_data))
    router.add(
        "GET",
        "/api/rs/testcase/2301",
        lambda _: httpx.Response(500, json={"error": "internal error"}),
    )
    router.add("GET", "/api/rs/testcase/2302", lambda _: _json_resp(good_detail))
    router.add("GET", "/api/rs/testcase/2302/scenario", lambda _: _json_resp([]))
    router.add("GET", "/api/rs/testcase/2302/step", lambda _: _json_resp([]))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))

    assert len(cases) == 1
    assert cases[0].id == "2302"


def test_graceful_fallback_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    list_data = {
        "content": [{"id": 2301, "name": "failing case"}],
        "totalPages": 1,
    }

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", lambda _: _json_resp(list_data))
    router.add("GET", "/api/rs/testcase/2301", lambda _: httpx.Response(500, json={}))

    connector = _make_connector(router)
    with caplog.at_level(logging.WARNING, logger="testops_mirror.connectors.allure_testops"):
        cases = list(connector.iter_test_cases(PROJECT_ID))

    assert cases == []
    assert any("2301" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 8. Empty project
# ---------------------------------------------------------------------------


def test_empty_project_yields_no_cases() -> None:
    empty_list = {"content": [], "totalPages": 1, "totalElements": 0}

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", lambda _: _json_resp(empty_list))

    connector = _make_connector(router)
    cases = list(connector.iter_test_cases(PROJECT_ID))

    assert cases == []


def test_empty_project_no_detail_requests() -> None:
    detail_calls: list[httpx.Request] = []

    def tracking_detail(req: httpx.Request) -> httpx.Response:
        detail_calls.append(req)
        return _json_resp(DETAIL_RESP)

    empty_list = {"content": [], "totalPages": 1}

    router = MockRouter()
    router.add("POST", "/api/uaa/oauth/token", _auth_handler)
    router.add("GET", "/api/rs/testcase", lambda _: _json_resp(empty_list))
    router.add("GET", "/api/rs/testcase/2301", tracking_detail)

    connector = _make_connector(router)
    list(connector.iter_test_cases(PROJECT_ID))

    assert detail_calls == []


# ---------------------------------------------------------------------------
# 9. Auth failure propagates immediately
# ---------------------------------------------------------------------------


def test_auth_error_on_401_propagates() -> None:
    router = MockRouter()
    router.add(
        "POST",
        "/api/uaa/oauth/token",
        lambda _: httpx.Response(401, json={"error": "unauthorized"}),
    )

    connector = _make_connector(router)
    with pytest.raises(AuthError):
        list(connector.iter_test_cases(PROJECT_ID))
