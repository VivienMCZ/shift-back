"""Tests des points d'entrée propres à ``app.main`` : la sonde /health et
l'exposition d'OpenAPI.

Le parsing de configuration (``get_env_int``, ``get_env_float``,
``mask_database_url``, ``get_env_bool``, ``get_env_list``) vit dans
``app.config`` et est testé dans ``test_config.py``.
"""


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "shift-back"}


def test_openapi_est_genere(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Shift API"
