async def test_register_creates_user_and_profile(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "password": "password123",
            "full_name": "New User",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


async def test_register_duplicate_email_fails(client):
    body = {"email": "dup@example.com", "password": "password123"}
    first = await client.post("/api/v1/auth/register", json=body)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=body)
    assert second.status_code == 400


async def test_register_short_password_fails(client):
    response = await client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert response.status_code == 422


async def test_login_success_and_failure(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "password123"},
    )
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "wrongpass1"},
    )
    assert bad.status_code == 401


async def test_me_requires_auth(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
