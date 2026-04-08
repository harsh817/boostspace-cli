"""API client for Boost.space / Make Integrator."""

import json
from typing import Any, Optional

import httpx

from .config import Config


class APIError(Exception):
    def __init__(self, status_code: int, message: str, detail: Any = None):
        self.status_code = status_code
        self.detail = detail
        self.code = _extract_error_code(detail)
        self.hint = _error_hint(status_code, self.code, detail)
        suffix = f" [{self.code}]" if self.code else ""
        msg = f"API error {status_code}{suffix}: {message}"
        if self.hint:
            msg = f"{msg} - {self.hint}"
        super().__init__(msg)


def _extract_error_code(detail: Any) -> Optional[str]:
    if isinstance(detail, dict):
        code = detail.get("code")
        return str(code) if code is not None else None
    return None


def _error_hint(status_code: int, code: Optional[str], detail: Any) -> str:
    if code == "IM015":
        return "Session expired or invalid. Run 'boost auth playwright'."
    if code == "IM007":
        return "Invalid blueprint/module. Run 'boost scenario repair' then validate."
    if code == "SC400":
        base = "Request validation failed. Check required fields and IDs."
        if isinstance(detail, dict):
            suberrors = detail.get("suberrors")
            if isinstance(suberrors, list) and suberrors:
                first = suberrors[0]
                if isinstance(first, dict) and first.get("message"):
                    return f"{base} {first['message']}"
                if isinstance(first, str):
                    return f"{base} {first}"
        return base
    if status_code == 401:
        return "Unauthorized. Run 'boost auth doctor --fix' or re-login."
    if status_code == 403:
        return "Forbidden in current context. Verify org/team access and CSRF session."
    if status_code == 404:
        return "Resource not found. Verify ID/name and organization scope."
    if status_code == 429:
        return "Rate limit hit. Wait and retry."

    if isinstance(detail, dict):
        suberrors = detail.get("suberrors")
        if isinstance(suberrors, list) and suberrors:
            first = suberrors[0]
            if isinstance(first, dict) and first.get("message"):
                return str(first["message"])

    return ""


class APIClient:
    """Unified API client using browser session cookies or OAuth token."""

    def __init__(self, config: Config):
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            headers=self._headers(),
            cookies=self._cookies(),
            timeout=30.0,
            follow_redirects=True,
        )

    def _cookies(self) -> dict[str, str]:
        raw = self.config.load_cookies() or []
        cookies: dict[str, str] = {}
        for c in raw:
            name = c.get("name")
            value = c.get("value")
            if name and value is not None:
                cookies[name] = value
        return cookies

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }

        if self.config.backend == "boostspace":
            origin = "https://integrator.boost.space"
            headers["Origin"] = origin
            headers["Referer"] = f"{origin}/organization/{self.config.organization_id or 14109}/dashboard"
        else:
            origin = self.config.zone_url.rstrip("/")
            headers["Origin"] = origin
            headers["Referer"] = f"{origin}/"

        cookies = self.config.load_cookies() or []

        # Prefer session-cookie auth; fallback to bearer token only when no cookies exist
        if not cookies and self.config.oauth_token:
            headers["Authorization"] = f"Bearer {self.config.oauth_token}"

        # XSRF header for session-cookie auth
        for c in cookies:
            if c.get("name") == "XSRF-TOKEN":
                headers["X-XSRF-TOKEN"] = c.get("value", "")
                break

        return headers

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise APIError(response.status_code, response.reason_phrase, detail)

        if not response.content:
            return {}

        try:
            return response.json()
        except Exception:
            return {"raw": response.text}

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None) -> dict:
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: Optional[dict] = None) -> dict:
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    def get_user(self) -> dict:
        return self.get("/users/me")

    def list_connections(self, team_id: Optional[int] = None) -> dict:
        params = {}
        if team_id:
            params["teamId"] = team_id
        return self.get("/connections", params=params)

    def list_scenarios(
        self,
        team_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        params = {"pg[limit]": limit, "pg[offset]": offset}
        if team_id:
            params["teamId"] = team_id
        elif organization_id:
            params["organizationId"] = organization_id
        return self.get("/scenarios", params=params)

    def get_scenario(self, scenario_id: int) -> dict:
        return self.get(f"/scenarios/{scenario_id}")

    def get_blueprint(self, scenario_id: int) -> dict:
        payload = self.get(f"/scenarios/{scenario_id}/blueprint")
        blueprint = self.extract_blueprint(payload)
        return blueprint or payload

    def create_scenario(
        self,
        team_id: int,
        blueprint: dict,
        scheduling: Optional[dict] = None,
        name: Optional[str] = None,
        folder_id: Optional[int] = None,
    ) -> dict:
        resolved_scheduling = scheduling or {"type": "on-demand"}
        payload = {
            "teamId": team_id,
            "blueprint": json.dumps(blueprint),
            "scheduling": json.dumps(resolved_scheduling),
        }
        if name:
            payload["name"] = name
        if folder_id is not None:
            payload["folderId"] = int(folder_id)
        return self.post("/scenarios", json=payload)

    def list_workspace_templates(
        self,
        team_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        limit: int = 50,
        query: Optional[str] = None,
        public_only: bool = False,
    ) -> dict:
        params: dict[str, Any] = {"pg[limit]": limit, "pg[offset]": 0}
        if team_id:
            params["teamId"] = team_id
        elif organization_id:
            params["organizationId"] = organization_id
        if query:
            params["q"] = query
        if public_only:
            params["public"] = True

        endpoints = ("/templates", "/scenario-templates", "/scenarios/templates")
        for endpoint in endpoints:
            try:
                payload = self.get(endpoint, params=params)
                if isinstance(payload, dict):
                    result = dict(payload)
                    result["_sourcePath"] = endpoint
                    return result
                return {"templates": payload, "_sourcePath": endpoint}
            except APIError as exc:
                if exc.status_code in {404, 405}:
                    continue
                raise

        return {"templates": [], "_sourcePath": None}

    def list_scenario_folders(
        self,
        team_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        limit: int = 200,
    ) -> dict:
        params: dict[str, Any] = {"pg[limit]": limit, "pg[offset]": 0}
        if team_id:
            params["teamId"] = team_id
        elif organization_id:
            params["organizationId"] = organization_id

        endpoints = ("/scenario-folders", "/folders", "/scenarios/folders")
        for endpoint in endpoints:
            try:
                payload = self.get(endpoint, params=params)
                if isinstance(payload, dict):
                    result = dict(payload)
                    result["_sourcePath"] = endpoint
                    return result
                return {"folders": payload, "_sourcePath": endpoint}
            except APIError as exc:
                if exc.status_code in {404, 405}:
                    continue
                raise

        return {"folders": [], "_sourcePath": None}

    def create_scenario_folder(
        self,
        name: str,
        team_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        parent_id: Optional[int] = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name}
        if team_id is not None:
            payload["teamId"] = team_id
        if organization_id is not None:
            payload["organizationId"] = organization_id
        if parent_id is not None:
            payload["parentId"] = parent_id

        endpoints = ("/scenario-folders", "/folders", "/scenarios/folders")
        last_error: APIError | None = None
        for endpoint in endpoints:
            try:
                return self.post(endpoint, json=payload)
            except APIError as exc:
                if exc.status_code in {404, 405}:
                    last_error = exc
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("No folder endpoint available")

    def update_scenario(self, scenario_id: int, updates: dict) -> dict:
        return self.patch(f"/scenarios/{scenario_id}", json=updates)

    def delete_scenario(self, scenario_id: int) -> dict:
        return self.delete(f"/scenarios/{scenario_id}")

    def clone_scenario(self, scenario_id: int, team_id: int, name: str) -> dict:
        return self.post(f"/scenarios/{scenario_id}/clone", json={"teamId": team_id, "name": name})

    def start_scenario(self, scenario_id: int) -> dict:
        return self.post(f"/scenarios/{scenario_id}/start")

    def stop_scenario(self, scenario_id: int) -> dict:
        return self.post(f"/scenarios/{scenario_id}/stop")

    def run_scenario(self, scenario_id: int, data: Optional[dict] = None, responsive: bool = True, callback_url: Optional[str] = None) -> dict:
        payload: dict = {"responsive": responsive}
        if data:
            payload["data"] = data
        if callback_url:
            payload["callbackUrl"] = callback_url
        return self.post(f"/scenarios/{scenario_id}/run", json=payload)

    def get_logs(self, scenario_id: int, limit: int = 20, status: Optional[int] = None) -> dict:
        params = {"pg[limit]": limit}
        if status is not None:
            params["status"] = status
        return self.get(f"/scenarios/{scenario_id}/logs", params=params)

    def get_execution(self, scenario_id: int, execution_id: str) -> dict:
        return self.get(f"/scenarios/{scenario_id}/executions/{execution_id}")

    def get_incomplete_executions(self, scenario_id: int) -> dict:
        return self.get(f"/scenarios/{scenario_id}/incomplete-executions")

    def list_webhooks(self) -> dict:
        return self.get("/webhooks")

    def create_webhook(self, name: str, scenario_id: int, hook_type: str = "custom", security: Optional[dict] = None) -> dict:
        payload = {
            "name": name,
            "scenarioId": scenario_id,
            "type": hook_type,
            "hookType": "HEAD",
            "security": security or {"type": "none"},
        }
        return self.post("/webhooks", json=payload)

    def delete_webhook(self, webhook_id: int) -> dict:
        return self.delete(f"/webhooks/{webhook_id}")

    def list_teams(self, organization_id: Optional[int] = None) -> dict:
        params = {}
        if organization_id:
            params["organizationId"] = organization_id
        return self.get("/teams", params=params)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
    @staticmethod
    def extract_blueprint(payload: Any) -> Optional[dict[str, Any]]:
        """Extract a blueprint dict from different API response shapes."""
        candidate: Any = payload
        if isinstance(payload, dict):
            if isinstance(payload.get("blueprint"), (dict, str)):
                candidate = payload.get("blueprint")
            elif isinstance(payload.get("response"), dict) and isinstance(payload["response"].get("blueprint"), (dict, str)):
                candidate = payload["response"].get("blueprint")
            elif isinstance(payload.get("scenario"), dict) and isinstance(payload["scenario"].get("blueprint"), (dict, str)):
                candidate = payload["scenario"].get("blueprint")

        if isinstance(candidate, str):
            try:
                parsed = json.loads(candidate)
            except Exception:
                return None
            if isinstance(parsed, dict):
                return parsed
            return None

        if isinstance(candidate, dict) and ("flow" in candidate or "modules" in candidate or "metadata" in candidate):
            return candidate

        return None
