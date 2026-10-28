from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_login_and_current_user(client: TestClient):
    login_as(client, "admin@testing.example.com")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_login_is_rate_limited_after_repeated_failures(client: TestClient):
    payload = {"email": "admin@testing.example.com", "password": "wrong-password"}
    for _ in range(5):
        response = client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 401
    blocked = client.post("/api/v1/auth/login", json=payload)
    assert blocked.status_code == 429


def test_logout_clears_session(client: TestClient):
    login_as(client, "admin@testing.example.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_admin_can_create_user_and_lead(client: TestClient):
    login_as(client, "admin@testing.example.com")
    user_response = client.post(
        "/api/v1/users",
        json={
            "email": "new@testing.example.com",
            "full_name": "New Manager",
            "password": "password123",
            "role": "manager",
        },
    )
    assert user_response.status_code == 201
    manager_id = user_response.json()["id"]
    lead_response = client.post(
        "/api/v1/leads",
        json={
            "phone": "+7 999 123-45-67",
            "name": "Иван",
            "source": "website",
            "manager_id": manager_id,
        },
    )
    assert lead_response.status_code == 201
    assert lead_response.json()["manager"]["id"] == manager_id


def test_manager_sees_only_own_leads(client: TestClient):
    login_as(client, "admin@testing.example.com")
    users = client.get("/api/v1/users").json()
    first_id = next(user["id"] for user in users if user["email"] == "manager@testing.example.com")
    second_id = next(user["id"] for user in users if user["email"] == "second@testing.example.com")
    for manager_id in (first_id, second_id):
        response = client.post(
            "/api/v1/leads",
            json={"phone": "+7 999 000-00-00", "source": "website", "manager_id": manager_id},
        )
        assert response.status_code == 201

    login_as(client, "manager@testing.example.com")
    leads = client.get("/api/v1/leads").json()
    assert leads["total"] == 1
    assert leads["items"][0]["manager_id"] == first_id
    assert client.get("/api/v1/leads/2").status_code == 404


def test_manager_cannot_manage_users_or_create_leads(client: TestClient):
    login_as(client, "manager@testing.example.com")
    assert client.get("/api/v1/users").status_code == 403
    response = client.post("/api/v1/leads", json={"phone": "+79990000000", "source": "website"})
    assert response.status_code == 403


def test_leads_are_automatically_balanced_between_available_managers(client: TestClient):
    login_as(client, "admin@testing.example.com")
    managers = client.get("/api/v1/users?role=manager").json()
    manager_ids = sorted(manager["id"] for manager in managers)

    assigned = []
    for index in range(2):
        response = client.post(
            "/api/v1/leads",
            json={
                "phone": f"+7 999 000-00-0{index}",
                "name": "Автолид",
                "comment": "Позвонить сегодня",
                "source": "website",
            },
        )
        assert response.status_code == 201
        assert response.json()["source"] == "website"
        assigned.append(response.json()["manager_id"])

    assert assigned == manager_ids


def test_day_off_excludes_manager_from_distribution(client: TestClient):
    login_as(client, "admin@testing.example.com")
    managers = client.get("/api/v1/users?role=manager").json()
    first, second = sorted(managers, key=lambda manager: manager["id"])
    response = client.patch(
        f"/api/v1/users/{first['id']}",
        json={"unavailable_until": "2099-12-31"},
    )
    assert response.status_code == 200

    lead = client.post("/api/v1/leads", json={"phone": "+7 999 111-22-33", "source": "phone"})
    assert lead.status_code == 201
    assert lead.json()["manager_id"] == second["id"]


def test_auto_distribution_fails_when_no_manager_is_available(client: TestClient):
    login_as(client, "admin@testing.example.com")
    managers = client.get("/api/v1/users?role=manager").json()
    for manager in managers:
        response = client.patch(f"/api/v1/users/{manager['id']}", json={"is_active": False})
        assert response.status_code == 200

    response = client.post("/api/v1/leads", json={"phone": "+7 999 111-22-44", "source": "OTHER"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Сейчас нет менеджеров на смене"
