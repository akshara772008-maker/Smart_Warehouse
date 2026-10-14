import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module
from os_modules.warehouse_engine import WarehouseEngine


previous_engine = app_module.engine
app_module.engine = WarehouseEngine()

try:
    client = app_module.app.test_client()
    initial = client.get("/resources").get_json()["resources"]
    assert initial == {
        "Worker": 5,
        "Forklift": 2,
        "Packing": 3,
        "Vehicle": 2
    }

    created = client.post("/create_order", json={
        "process_id": "P_RESOURCE",
        "order_id": "O_RESOURCE",
        "arrival_time": 0,
        "burst_time": 5,
        "priority": 1,
        "resources": ["Forklift"]
    })
    assert created.status_code == 200, created.get_json()

    allocated = client.post("/allocate", json={
        "process_id": "P_RESOURCE",
        "resources": ["Forklift"]
    })
    assert allocated.status_code == 200, allocated.get_json()
    assert allocated.get_json()["available_resources"]["Forklift"] == 1

    repeated = client.post("/allocate", json={
        "process_id": "P_RESOURCE",
        "resources": ["Forklift"]
    })
    assert repeated.status_code == 409
    assert client.get("/resources").get_json()["resources"]["Forklift"] == 1

    released = client.post("/release", json={"process_id": "P_RESOURCE"})
    assert released.status_code == 200, released.get_json()
    assert released.get_json()["available_resources"]["Forklift"] == 2

    repeated_release = client.post(
        "/release", json={"process_id": "P_RESOURCE"}
    )
    assert repeated_release.status_code == 409
    assert client.get("/resources").get_json()["resources"]["Forklift"] == 2
finally:
    app_module.engine = previous_engine

print("RESOURCE API TEST PASSED")
