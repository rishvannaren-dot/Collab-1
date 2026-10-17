"""Helpers shared by the tests: import with `from tests.helpers import ...`."""

import re


def csrf_token(client, path):
    """The CSRF token from the first form on `path`."""
    html = client.get(path).data.decode()
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def register(client, username="alice", password="longenough1"):
    return client.post(
        "/auth/register",
        data={"username": username, "password": password, "consent": "on"},
    )


def login(client, username="alice", password="longenough1"):
    return client.post("/auth/login", data={"username": username, "password": password})


def make_student(client, username="alice", grade=12, goal="jee", interests=("science-tech", "sports")):
    """Register, sign in and finish onboarding (CSRF must be off for this client)."""
    register(client, username)
    login(client, username)
    client.post(
        "/onboarding",
        data={"interests": list(interests), "grade": str(grade), "goal": goal},
    )
    return client
