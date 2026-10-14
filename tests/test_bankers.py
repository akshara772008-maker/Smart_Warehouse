import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module
from os_modules.warehouse_engine import WarehouseEngine

previous_engine = app_module.engine
app_module.engine = WarehouseEngine()

client = app_module.app.test_client()
created = client.post("/create_order", json={
    "process_id": "P_BANKER",
    "order_id": "O_BANKER",
    "arrival_time": 0,
    "burst_time": 5,
    "priority": 1,
    "resources": ["Worker"]
})
assert created.status_code == 200, created.get_json()

started = client.post("/run_process", json={"process_id": "P_BANKER"})
assert started.status_code == 200, started.get_json()
response = client.post("/banker")
app_module.engine = previous_engine

assert response.status_code == 200, response.get_json()
result = response.get_json()
assert result["success"] is True
assert result["safe"] is True
assert result["safe_sequence"] == ["P_BANKER"]
assert result["allocation"]["P_BANKER"]["Worker"] == 1

print("BANKER API TEST PASSED")
