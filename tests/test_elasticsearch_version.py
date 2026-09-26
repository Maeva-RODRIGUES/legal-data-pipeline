from pathlib import Path

import elasticsearch
import yaml

COMPOSE = Path(__file__).parent.parent / "docker-compose.yml"


def server_major() -> int:
    with COMPOSE.open(encoding="utf-8") as f:
        image = yaml.safe_load(f)["services"]["elasticsearch"]["image"]
    return int(image.rsplit(":", 1)[1].split(".")[0])


def test_client_major_matches_server_image():
    client = elasticsearch.__versionstr__
    server = server_major()
    assert int(client.split(".")[0]) == server, (
        f"elasticsearch client {client} does not match the server image "
        f"major version {server} in docker-compose.yml: "
        f"pin elasticsearch>={server},<{server + 1} in requirements.txt"
    )
