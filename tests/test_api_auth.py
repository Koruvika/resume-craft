import httpx

REGISTER = {"email": "user@example.com", "password": "a-very-long-passphrase"}
LOGIN = {"email": "user@example.com", "password": "a-very-long-passphrase"}


async def _register(plain_client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    return await plain_client.post("/api/v1/auth/register", json=payload)


async def _login(plain_client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    return await plain_client.post("/api/v1/auth/login", json=payload)


async def test_register_returns_user(plain_client: httpx.AsyncClient) -> None:
    response = await _register(plain_client, REGISTER)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["is_active"] is True
    assert "password" not in body


async def test_register_conflict_on_duplicate_email(plain_client: httpx.AsyncClient) -> None:
    assert (await _register(plain_client, REGISTER)).status_code == 201
    response = await _register(plain_client, REGISTER)
    assert response.status_code == 409


async def test_register_rejects_short_password(plain_client: httpx.AsyncClient) -> None:
    response = await _register(plain_client, {"email": "x@example.com", "password": "short"})
    assert response.status_code == 422


async def test_login_returns_token(plain_client: httpx.AsyncClient) -> None:
    await _register(plain_client, REGISTER)
    response = await _login(plain_client, LOGIN)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["access_token"]


async def test_login_rejects_wrong_password(plain_client: httpx.AsyncClient) -> None:
    await _register(plain_client, REGISTER)
    response = await _login(
        plain_client, {"email": "user@example.com", "password": "not-the-right-one"}
    )
    assert response.status_code == 401


async def test_login_rejects_unknown_email(plain_client: httpx.AsyncClient) -> None:
    response = await _login(
        plain_client, {"email": "ghost@example.com", "password": "whatever-passphrase"}
    )
    assert response.status_code == 401


async def test_me_with_real_token(plain_client: httpx.AsyncClient) -> None:
    await _register(plain_client, REGISTER)
    token = (await _login(plain_client, LOGIN)).json()["access_token"]
    response = await plain_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


async def test_me_without_token_is_401(plain_client: httpx.AsyncClient) -> None:
    response = await plain_client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_register_then_generate_resume_full_flow(
    plain_client: httpx.AsyncClient, monkeypatch
) -> None:
    """Token from /auth/login works on the domain endpoints too (real auth path)."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "resumecraft.api.v1.resumes.celery_app.send_task",
        lambda name, args=None, kwargs=None, **_: SimpleNamespace(id="fake-task-id"),
    )
    await _register(plain_client, REGISTER)
    token = (await _login(plain_client, LOGIN)).json()["access_token"]
    response = await plain_client.post(
        "/api/v1/resumes/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_text": "x" * 60,
            "target_role": "Backend Engineer",
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    response = await plain_client.get(
        f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
