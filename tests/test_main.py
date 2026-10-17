def test_index_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/welcome")


def test_static_css(client):
    assert client.get("/static/style.css").status_code == 200
