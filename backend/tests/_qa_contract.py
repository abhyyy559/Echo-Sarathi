"""Shared contract-test helpers for the Lane E backend suites.

Imports whatever FastAPI app Lane A has merged so far and binds an in-memory
SQLite session factory to it (never touches real Postgres). Every step fails
soft: callers get ``(value_or_None, reason)`` so suites can skip with an
informative message while lanes land concurrently.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import pytest

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
BACKEND_DIR: Path = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

ABSENT_STUDENT_PATH: Path = PROJECT_ROOT / "domain-configs" / "absent-student.json"

AUTH_REGISTER: str = "/api/auth/register"
AUTH_LOGIN: str = "/api/auth/login"
DEFAULT_MEMBER_PASSWORD: str = "test-password-1"


def load_absent_student_config() -> dict[str, Any]:
    with ABSENT_STUDENT_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_version_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Map a domain-config file onto the frozen AgentVersion payload shape."""
    disclosure = config.get("disclosure_script") or config.get("mandatory_disclosure") or ""
    return {
        "system_prompt": config.get("system_prompt", ""),
        "company_context": config.get("company_context", {}),
        "question_flow": config.get("question_flow", []),
        "extraction_schema": config.get("extraction_schema", {}),
        "disclosure_script": disclosure,
        "escalation_rules": config.get("escalation_rules", []),
        "voice_settings": config.get("voice_settings", {}),
    }


def import_first(candidates: list[tuple[str, str]]) -> tuple[Optional[Any], str]:
    """Try ``(module, attr)`` pairs in order; return the first hit or why all failed."""
    failures: list[str] = []
    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            failures.append(f"{mod_name}: {type(exc).__name__}: {exc}")
            continue
        obj = getattr(mod, attr, None)
        if obj is not None:
            return obj, ""
        failures.append(f"{mod_name}.{attr}: attribute missing")
    return None, "; ".join(failures)


def qa_settings() -> Any:
    """Hermetic Settings mirroring backend/tests/conftest.py defaults (no .env IO)."""
    from app.config import Settings

    return Settings(
        database_url="sqlite://",
        jwt_secret="qa_test_jwt_secret",
        jwt_expire_minutes=60,
        internal_api_token="qa_internal_token",
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="devsecret",
        cors_origins="http://localhost:3000",
        dialer_enabled=False,
        _env_file=None,
    )


def _prefer_backend_app_package() -> None:
    """Ensure ``import app.*`` resolves to /backend even when another lane put
    its own ``app`` package first on sys.path (both lanes ship one).

    Purging is only needed when the imported package is a foreign copy. Nuking
    a correct install would re-import every module, splitting class identities
    (``GoogleTokenError``, module-level references held by other test modules)
    from the objects the shared fixtures already imported.
    """
    if str(BACKEND_DIR) in sys.path:
        sys.path.remove(str(BACKEND_DIR))
    sys.path.insert(0, str(BACKEND_DIR))
    imported = sys.modules.get("app")
    imported_file = getattr(imported, "__file__", None)
    if imported_file is not None:
        try:
            if Path(imported_file).resolve().is_relative_to(BACKEND_DIR):
                return
        except OSError:
            pass
    for name in [n for n in list(sys.modules) if n == "app" or n.startswith("app.")]:
        del sys.modules[name]


def import_app() -> tuple[Optional[Any], str]:
    """Locate the merged FastAPI app or app factory, or explain why not."""
    _prefer_backend_app_package()
    create_app, why_factory = import_first(
        [("app.main", "create_app"), ("main", "create_app")]
    )
    if create_app is not None:
        try:
            app = create_app()
        except TypeError:
            try:
                app = create_app(qa_settings())
            except Exception as exc:
                return None, f"create_app(settings) failed ({type(exc).__name__}: {exc})"
        except Exception as exc:
            return None, f"create_app() failed ({type(exc).__name__}: {exc})"
        if hasattr(app, "routes"):
            return app, ""
    app, why_attr = import_first([("app.main", "app"), ("main", "app")])
    if app is not None and hasattr(app, "routes"):
        return app, ""
    return None, f"FastAPI app not importable yet (factory: {why_factory}; attr: {why_attr})"


def expect_merged(result: Optional[Any], why: str, lane: str = "Lane A") -> Any:
    """Skip when a frozen-contract seam is simply not merged yet; fail otherwise."""
    if result is not None:
        return result
    lowered = why.lower()
    if "missing" in lowered or "not merged" in lowered or "no member" in lowered or "404" in lowered:
        pytest.skip(f"[{lane}] {why}")
    pytest.fail(f"[{lane}] unexpected contract break: {why}")


def build_test_client(app: Any) -> tuple[Optional[Any], str]:
    """Bind an in-memory SQLite session factory to ``app`` and wrap a TestClient."""
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:
        return None, f"TestClient/httpx unavailable: {exc}"
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
    except Exception as exc:
        return None, f"sqlalchemy unavailable: {exc}"

    base, base_reason = import_first(
        [("app.models", "Base"), ("models", "Base"), ("app.database", "Base")]
    )
    if base is None:
        return None, f"ORM Base not located ({base_reason})"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        base.metadata.create_all(engine)
    except Exception as exc:
        return None, (
            "models not creatable on SQLite yet "
            f"({type(exc).__name__}: {exc}); Lane A conftest owns the canonical fixture"
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    bound = False
    try:
        app.state.session_factory = factory
        bound = True
    except Exception:
        pass
    get_db, _gdb_reason = import_first([("app.database", "get_db"), ("database", "get_db")])
    if get_db is not None:
        def _override() -> Any:
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override
        bound = True
    if not bound:
        return None, "could not rebind sessions (neither app.state.session_factory nor get_db override)"

    client = TestClient(app, raise_server_exceptions=False)
    settings_obj = getattr(getattr(app, "state", None), "settings", None)
    client.qa_context = {
        "engine": engine,
        "session_factory": factory,
        "settings": settings_obj,
    }
    return client, ""


def api(
    client: Any,
    method: str,
    url: str,
    token: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    headers = dict(kwargs.pop("headers", {}) or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.request(method, url, headers=headers, **kwargs)


def extract_token(payload: dict[str, Any]) -> Optional[str]:
    token = payload.get("token") or payload.get("access_token")
    return token if isinstance(token, str) and token else None


def register_org(
    client: Any,
    *,
    org_name: str,
    email: str,
    password: str = "test-password-1",
) -> tuple[Optional[dict[str, Any]], str]:
    resp = client.post(
        AUTH_REGISTER, json={"org_name": org_name, "email": email, "password": password}
    )
    if resp.status_code == 404:
        return None, "register route missing (auth router not merged yet)"
    if resp.status_code not in (200, 201):
        return None, f"register failed {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    token = extract_token(data if isinstance(data, dict) else {})
    if not token:
        return None, f"register response missing token: {str(data)[:300]}"
    return {
        "token": token,
        "user": data.get("user", {}) if isinstance(data, dict) else {},
        "email": email,
        "password": password,
        "org": (data.get("user", {}) or {}).get("org_id"),
    }, ""


def create_agent(client: Any, token: str, name: str) -> tuple[Optional[dict[str, Any]], str]:
    resp = api(client, "POST", "/api/agents", token=token,
               json={"name": name, "description": "qa contract test agent"})
    if resp.status_code == 404:
        return None, "/api/agents route missing (agents router not merged yet)"
    if resp.status_code not in (200, 201):
        return None, f"agent create failed {resp.status_code}: {resp.text[:300]}"
    return resp.json(), ""


def create_version(
    client: Any,
    token: str,
    agent_id: Any,
    overrides: Optional[dict[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], str]:
    payload = build_version_payload(load_absent_student_config())
    payload.update(overrides or {})
    resp = api(client, "POST", f"/api/agents/{agent_id}/versions", token=token, json=payload)
    if resp.status_code == 404:
        return None, f"POST /api/agents/{agent_id}/versions missing (router not merged yet)"
    if resp.status_code not in (200, 201):
        return None, f"version create failed {resp.status_code}: {resp.text[:400]}"
    return resp.json(), ""


_MEMBER_PATH_RE = re.compile(r"user|invite|member", re.IGNORECASE)


def mint_token_without_org(
    subject: Any,
    settings: Any = None,
) -> tuple[Optional[str], str]:
    """Best-effort JWT that is correctly signed but carries NO usable org claim."""
    if settings is None:
        try:
            settings = qa_settings()
        except Exception as exc:
            return None, f"cannot build settings ({exc})"
    attempts: list[tuple[tuple[Any, ...], str]] = [
        (({"sub": str(subject)},), "dict-payload"),
        ((str(subject),), "subject-string"),
    ]
    try:
        numeric = int(subject)
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None:
        attempts.append(((numeric, None, "member", settings), "user_id,org_id=None,role,settings"))
        attempts.append(((numeric, "", "member", settings), "user_id,empty-org,role,settings"))
    failures: list[str] = []
    for mod_name in ("app.auth", "auth", "app.deps", "deps"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for fname in ("create_access_token", "create_token", "_create_token"):
            fn = getattr(mod, fname, None)
            if not callable(fn):
                continue
            for args, label in attempts:
                try:
                    token = fn(*args)
                except TypeError as exc:
                    failures.append(f"{fname}({label}): {exc}")
                    continue
                except Exception as exc:
                    failures.append(f"{fname}({label}): {type(exc).__name__}: {exc}")
                    break
                if isinstance(token, str) and token.count(".") == 2:
                    return token, ""
    try:
        import jwt

        secret = getattr(settings, "jwt_secret", "")
        if secret:
            import datetime as _dt

            token = jwt.encode(
                {
                    "sub": str(subject),
                    "iat": _dt.datetime.now(_dt.timezone.utc),
                    "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1),
                },
                secret,
                algorithm=getattr(settings, "jwt_algorithm", "HS256"),
            )
            return token, ""
    except Exception as exc:
        failures.append(f"raw-jwt fallback: {exc}")
    return None, "; ".join(failures) or "no token issuer discoverable"


def _provision_member_via_openapi(
    client: Any,
    owner: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], str]:
    """Create a role=member user via a discovered invite-style endpoint, then log in."""
    try:
        spec_resp = client.get("/openapi.json")
        spec = spec_resp.json()
    except Exception as exc:
        return None, f"openapi unavailable ({exc})"
    paths = [
        path
        for path, ops in (spec.get("paths") or {}).items()
        if isinstance(ops, dict) and "post" in ops and _MEMBER_PATH_RE.search(path)
    ]
    member_email = f"member-{uuid.uuid4().hex[:8]}@example.com"
    for path in sorted(paths):
        resp = api(
            client,
            "POST",
            path,
            token=owner["token"],
            json={"email": member_email, "password": DEFAULT_MEMBER_PASSWORD, "role": "member"},
        )
        if resp.status_code not in (200, 201):
            continue
        login = client.post(
            AUTH_LOGIN, json={"email": member_email, "password": DEFAULT_MEMBER_PASSWORD}
        )
        token = extract_token(login.json()) if login.status_code in (200, 201) else None
        if token:
            return {"token": token, "user": {"role": "member", "email": member_email}}, ""
        return None, f"member created via {path} but login failed {login.status_code}"
    return None, (
        "no member-provisioning endpoint advertised in OpenAPI "
        f"(scanned POST paths matching {_MEMBER_PATH_RE.pattern})"
    )


def provision_member(
    client: Any,
    owner: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], str]:
    api_result, api_why = _provision_member_via_openapi(client, owner)
    if api_result is not None:
        return api_result, ""
    db_result, db_why = provision_member_via_db(client, owner)
    if db_result is not None:
        return db_result, ""
    return None, f"openapi path: {api_why}; direct-db fallback: {db_why}"


def provision_member_via_db(client: Any, owner: dict[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    """Insert a role=member User row directly and mint a proper JWT for them."""
    ctx = getattr(client, "qa_context", None)
    if not ctx:
        return None, "no db harness context attached to client"
    try:
        from app.auth import create_access_token, hash_password
        from app.models import User

        email = f"member-{uuid.uuid4().hex[:8]}@example.com"
        password = DEFAULT_MEMBER_PASSWORD
        org_id = owner.get("org")
        factory = ctx["session_factory"]
        session = factory()
        try:
            if org_id is None:
                first = session.query(User).first()
                org_id = first.org_id if first is not None else None
            user = User(
                org_id=org_id,
                email=email,
                password_hash=hash_password(password),
                role="member",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id, resolved_org = int(user.id), int(user.org_id)
        finally:
            session.close()
        settings = ctx.get("settings") or qa_settings()
        token = create_access_token(user_id, resolved_org, "member", settings)
        return {"token": token, "user": {"id": user_id, "role": "member", "email": email}}, ""
    except Exception as exc:
        return None, f"direct-db member provisioning failed ({type(exc).__name__}: {exc})"
