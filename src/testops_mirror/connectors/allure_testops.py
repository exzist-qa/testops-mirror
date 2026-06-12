"""Allure TestOps connector.

Implements the TmsConnector protocol for Allure TestOps instances.

API paths are defined as module-level constants — verify them against your
instance's Swagger UI (<endpoint>/swagger-ui/) as paths may differ between
TestOps versions.

Authentication flow (confirmed by official docs):
  POST /api/uaa/oauth/token  (form: grant_type=apitoken, scope=openid, token=<api_token>)
  -> { access_token, expires_in }
  The JWT is then used as Bearer for all /api/rs/* requests.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from testops_mirror.exceptions import AuthError, ConnectorError, NotFoundError, RateLimitError
from testops_mirror.models import Link, Step, TestCase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API path constants
# Verify against <endpoint>/swagger-ui/ for your TestOps version.
# ---------------------------------------------------------------------------
_PATH_TOKEN = "/api/uaa/oauth/token"
_PATH_TESTCASE_LIST = "/api/rs/testcase"  # ?projectId=&page=&size=
_PATH_TESTCASE_DETAIL = "/api/rs/testcase/{id}"
_PATH_TESTCASE_SCENARIO = "/api/rs/testcase/{id}/scenario"
_PATH_TESTCASE_STEP = "/api/rs/testcase/{id}/step"

_PAGE_SIZE = 100
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubled on each attempt
_TOKEN_REFRESH_BUFFER = 60  # seconds before expiry to proactively refresh


class AllureTestOpsConnector:
    """Connector for Allure TestOps.

    Parameters
    ----------
    endpoint:
        Base URL of the TestOps instance, e.g. ``https://testops.example.com``.
    api_token:
        API token generated in TestOps → Profile → API tokens.
    suite_field:
        Name of the custom field used to derive the folder hierarchy.
        Values like ``"Shipments/Negative"`` are split on ``/`` to produce
        nested directories.
    """

    def __init__(
        self,
        endpoint: str,
        api_token: str,
        suite_field: str = "Suite",
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_token = api_token
        self._suite_field = suite_field
        self._client = http_client or httpx.Client(timeout=30)
        self._jwt: str | None = None
        self._jwt_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _authenticate(self) -> None:
        """Exchange the API token for a short-lived JWT."""
        url = self._endpoint + _PATH_TOKEN
        try:
            resp = self._client.post(
                url,
                data={
                    "grant_type": "apitoken",
                    "scope": "openid",
                    "token": self._api_token,
                },
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Auth request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            raise AuthError(f"Authentication failed ({resp.status_code}): {resp.text}")
        if not resp.is_success:
            raise ConnectorError(f"Auth endpoint returned {resp.status_code}: {resp.text}")

        data = resp.json()
        self._jwt = data["access_token"]
        expires_in: int = data.get("expires_in", 3600)
        self._jwt_expires_at = time.monotonic() + expires_in

    def _get_bearer(self) -> str:
        """Return a valid JWT, refreshing proactively if close to expiry."""
        if self._jwt is None or time.monotonic() >= self._jwt_expires_at - _TOKEN_REFRESH_BUFFER:
            self._authenticate()
        assert self._jwt is not None
        return self._jwt

    # ------------------------------------------------------------------
    # HTTP with retry
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send an authenticated request with retry logic.

        Retries on 429 and 5xx up to _MAX_RETRIES times using exponential
        backoff.  On 401 attempts one token refresh before retrying.
        Raises typed exceptions for all terminal error conditions.
        """
        url = self._endpoint + path
        delay = _RETRY_BASE_DELAY
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            headers = {"Authorization": f"Bearer {self._get_bearer()}"}
            try:
                resp = self._client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                continue

            if resp.status_code == 401:
                if attempt < _MAX_RETRIES - 1:
                    # Force token refresh and retry once
                    self._jwt = None
                    continue
                raise AuthError(f"Persistent 401 on {path}")

            if resp.status_code == 403:
                raise AuthError(f"Forbidden (403) on {path}")

            if resp.status_code == 404:
                raise NotFoundError(f"Resource not found: {path}")

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", delay))
                logger.warning("Rate limited (429); sleeping %.1fs", retry_after)
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(retry_after)
                    delay *= 2
                    last_exc = RateLimitError(f"Rate limit on {path}")
                    continue
                raise RateLimitError(f"Rate limit exceeded after {_MAX_RETRIES} attempts on {path}")

            if resp.status_code >= 500:
                logger.warning(
                    "Server error %d on %s; attempt %d/%d",
                    resp.status_code,
                    path,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    last_exc = ConnectorError(f"Server error {resp.status_code} on {path}")
                    continue
                raise ConnectorError(
                    f"Server error {resp.status_code} after {_MAX_RETRIES} attempts on {path}"
                )

            if not resp.is_success:
                raise ConnectorError(f"Unexpected {resp.status_code} on {path}: {resp.text}")

            return resp

        if last_exc is not None:
            raise ConnectorError(f"All {_MAX_RETRIES} attempts failed for {path}") from last_exc
        raise ConnectorError(f"Request failed for {path}")  # unreachable, satisfies mypy

    # ------------------------------------------------------------------
    # Steps — fallback chain
    # ------------------------------------------------------------------

    def _fetch_steps(self, case_id: str) -> list[dict[str, Any]]:
        """Fetch steps using a fallback chain.

        Known bug in some TestOps versions: /scenario returns empty steps.
        See: github.com/orgs/allure-framework/discussions/3190
        Try /scenario first; if the result is empty fall back to /step.
        4xx responses are silently ignored (return empty list).
        """
        for path_tpl in (_PATH_TESTCASE_SCENARIO, _PATH_TESTCASE_STEP):
            path = path_tpl.format(id=case_id)
            try:
                resp = self._request("GET", path)
                data = resp.json()
                steps: list[dict[str, Any]] = (
                    data if isinstance(data, list) else data.get("steps", data.get("content", []))
                )
                if steps:
                    return steps
            except (NotFoundError, ConnectorError):
                pass
        return []

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_status(raw: Any) -> str | None:
        if isinstance(raw, dict):
            return str(raw["name"]) if "name" in raw else None
        if isinstance(raw, str):
            return raw or None
        return None

    @staticmethod
    def _extract_tags(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    result.append(str(name))
            elif isinstance(item, str) and item:
                result.append(item)
        return result

    def _extract_custom_fields(self, raw: Any) -> dict[str, list[str]]:
        """Extract custom fields from the API response.

        Expected shape (verify against your instance):
          customFields[].customField.name  — field name
          customFields[].name              — field value
        """
        if not isinstance(raw, list):
            return {}
        result: dict[str, list[str]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            cf = item.get("customField", {})
            field_name: str = cf.get("name", "") if isinstance(cf, dict) else ""
            value: str = item.get("name", "")
            if field_name and value:
                result.setdefault(field_name, []).append(value)
        return result

    def _extract_suite_path(self, custom_fields: dict[str, list[str]]) -> tuple[str, ...]:
        """Derive suite folder path from the configured custom field.

        A value of ``"Shipments/Negative"`` becomes ``("Shipments", "Negative")``.
        Cases without the field land in the repo root.
        """
        values = custom_fields.get(self._suite_field, [])
        if not values:
            return ()
        # Use the first value; split on "/" for nested paths
        return tuple(part.strip() for part in values[0].split("/") if part.strip())

    @staticmethod
    def _map_steps(raw: list[dict[str, Any]]) -> list[Step]:
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name: str = item.get("name") or item.get("keyword") or ""
            if not name:
                continue
            expected: str | None = item.get("expectedResult") or item.get("expected_result") or None
            nested_raw: list[dict[str, Any]] = item.get("steps", [])
            result.append(
                Step(
                    name=name,
                    expected_result=expected,
                    steps=AllureTestOpsConnector._map_steps(nested_raw),
                )
            )
        return result

    @staticmethod
    def _map_links(raw: Any) -> list[Link]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url: str = item.get("url", "")
            if not url:
                continue
            result.append(
                Link(
                    name=item.get("name") or None,
                    url=url,
                    type=item.get("type") or None,
                )
            )
        return result

    def _map_case(
        self,
        detail: dict[str, Any],
        steps_raw: list[dict[str, Any]],
        project_id: str,
    ) -> TestCase:
        case_id = str(detail["id"])
        custom_fields = self._extract_custom_fields(detail.get("customFields"))
        suite_path = self._extract_suite_path(custom_fields)

        return TestCase(
            id=case_id,
            name=detail.get("name", ""),
            description=detail.get("description") or None,
            precondition=detail.get("precondition") or None,
            expected_result=detail.get("expectedResult") or None,
            status=self._extract_status(detail.get("status")),
            automated=bool(detail.get("automated", False)),
            tags=self._extract_tags(detail.get("tags")),
            custom_fields=custom_fields,
            links=self._map_links(detail.get("links")),
            suite_path=suite_path,
            steps=self._map_steps(steps_raw),
            source_url=f"{self._endpoint}/project/{project_id}/test-cases/{case_id}",
            source_project=project_id,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def iter_test_cases(self, project_id: str) -> Iterator[TestCase]:
        """Yield all test cases for *project_id*.

        Fetches the full list page by page, then loads details and steps for
        each case.  A ConnectorError on a single case is logged as WARNING and
        that case is skipped; it does not abort the entire sync.

        Raises AuthError immediately if token exchange fails — this is not
        recoverable per-case.
        """
        page = 0
        while True:
            resp = self._request(
                "GET",
                _PATH_TESTCASE_LIST,
                params={"projectId": project_id, "page": page, "size": _PAGE_SIZE},
            )
            data = resp.json()
            items: list[dict[str, Any]] = data.get("content", [])
            total_pages: int = data.get("totalPages", 1)

            for item in items:
                case_id = str(item.get("id", ""))
                if not case_id:
                    continue
                try:
                    detail_resp = self._request("GET", _PATH_TESTCASE_DETAIL.format(id=case_id))
                    detail: dict[str, Any] = detail_resp.json()
                    steps_raw = self._fetch_steps(case_id)
                    yield self._map_case(detail, steps_raw, project_id)
                except AuthError:
                    raise
                except Exception as exc:
                    logger.warning("Skipping test case %s due to error: %s", case_id, exc)
                    continue

            page += 1
            if page >= total_pages:
                break
