import os
import secrets
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from os_modules.warehouse_engine import WarehouseEngine

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SMART_WAREHOUSE_SECRET_KEY",
    secrets.token_hex(32)
)

state_path = os.environ.get("SMART_WAREHOUSE_STATE_PATH")
if state_path is None:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    state_path = str(
        local_app_data / "SmartWarehouse" / "warehouse_state.sqlite3"
    )
engine = WarehouseEngine(state_path)
def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _parse_integer(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create_order", methods=["POST"])
def create_order():
    active_engine = engine
    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400

    process_id = data.get("process_id")
    order_id = data.get("order_id")
    resources = data.get("resources", [])

    if (
        not isinstance(process_id, str)
        or not process_id.strip()
        or not isinstance(order_id, str)
        or not order_id.strip()
    ):
        return jsonify({
            "success": False,
            "message": "Process ID and Order ID are required"
        }), 400
    process_id = process_id.strip()
    order_id = order_id.strip()

    if active_engine.process_manager.get_process(process_id):
        return jsonify({
            "success": False,
            "message": f"Process ID '{process_id}' already exists"
        }), 409

    if not isinstance(resources, list):
        return jsonify({
            "success": False,
            "message": "Resources must be a list"
        }), 400
    if any(
        not isinstance(resource, str)
        or resource not in active_engine.resource_manager.resources
        for resource in resources
    ):
        return jsonify({
            "success": False,
            "message": "Resources contain an unknown resource name"
        }), 400
    try:
        arrival_time = _parse_integer(data.get("arrival_time", 0), "Arrival time")
        burst_time = _parse_integer(data.get("burst_time", 1), "Burst time")
        priority = _parse_integer(data.get("priority", 1), "Priority")

        process = active_engine.create_order(
            process_id,
            order_id,
            arrival_time,
            burst_time,
            priority,
            resources
        )

        return jsonify({
            "success": True,
            "message": (
                f"Order {process.order_id} for process "
                f"{process.process_id} created successfully."
            ),
            "process_id": process.process_id,
            "order_id": process.order_id,
            "state": process.state
        }), 200

    except (TypeError, ValueError) as error:
        return jsonify({
            "success": False,
            "message": str(error) if str(error) else "Numeric fields must contain valid numbers"
        }), (
            409
            if str(error).startswith("Process ID '")
            or str(error).startswith("Order ID '")
            else 400
        )




@app.route("/status", methods=["GET"])
def status():
    active_engine = engine
    resource_manager = active_engine.resource_manager
    with resource_manager.lock:
        processes = active_engine.process_manager.get_all_processes()
        available_resources = resource_manager.get_all_resources()
        total_resources = resource_manager.get_total_resources()
        allocations = {
            process_id: resources.copy()
            for process_id, resources in resource_manager.allocated.items()
        }
        maximum_claims = {
            process_id: claims.copy()
            for process_id, claims in active_engine.maximum_claims.items()
        }
        pending_requests = {
            process_id: resources.copy()
            for process_id, resources
            in resource_manager.pending_requests.items()
        }

    process_data = []

    for process in processes:
        holdings = allocations.get(process.process_id, [])
        process_data.append({
            "process_id": process.process_id,
            "order_id": process.order_id,
            "arrival_time": process.arrival_time,
            "burst_time": process.burst_time,
            "priority": process.priority,
            "state": process.state,
            "waiting_time": process.waiting_time,
            "turnaround_time": process.turnaround_time,
            "completion_time": process.completion_time,
            "required_resources": process.required_resources,
            "maximum_claim": maximum_claims.get(process.process_id, {}),
            "pending_requests": pending_requests.get(
                process.process_id, []
            ),
            "allocated_resources": {
                resource: holdings.count(resource)
                for resource in total_resources
            }
        })

    return jsonify({
        "success": True,
        "processes": process_data,
        "resources": available_resources,
        "total_resources": total_resources
    })


@app.route("/reset", methods=["POST"])
def reset_warehouse():
    try:
        result = engine.reset_warehouse()
    except ValueError as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 409

    return jsonify({
        "success": True,
        "message": "Warehouse data reset successfully.",
        "process_count": 0,
        "resources": result["available_resources"],
        "total_resources": result["total_resources"]
    })


@app.route("/schedule", methods=["POST"])
def schedule():
    active_engine = engine
    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400

    algorithm = data.get("algorithm", "FCFS")
    if not isinstance(algorithm, str) or not algorithm.strip():
        return jsonify({
            "success": False,
            "message": "Scheduling algorithm must be a non-empty string"
        }), 400
    algorithm = algorithm.strip().upper()

    try:
        time_quantum = _parse_integer(
            data.get("time_quantum", data.get("quantum", 2)),
            "Round Robin time quantum"
        )
        if time_quantum <= 0:
            raise ValueError(
                "Round Robin time quantum must be a positive integer"
            )
    except ValueError as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400

    try:
        result = active_engine.schedule_orders(algorithm, time_quantum)

        schedule_data = []

        for process in result["processes"]:

            schedule_data.append({

                "process_id":
                    process.process_id,

                "order_id":
                    process.order_id,

                "arrival_time":
                    process.arrival_time,

                "burst_time":
                    process.burst_time,

                "priority":
                    process.priority,

                "waiting_time":
                    process.waiting_time,

                "turnaround_time":
                    process.turnaround_time,

                "completion_time":
                    process.completion_time,

                "state":
                    process.state

            })

        return jsonify({

            "success": True,

            "algorithm":
                algorithm,

            "results":
                schedule_data,

            "average_waiting_time":
                result["average_waiting_time"],

            "average_turnaround_time":
                result["average_turnaround_time"]

        })

    except ValueError as error:

        return jsonify({

            "success": False,

            "message":
                str(error)

        }), 400



@app.route("/allocate", methods=["POST"])
def allocate_resource():
    active_engine = engine
    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400

    process_id = data.get("process_id")
    resources = data.get("resources", [])

    if not isinstance(process_id, str) or not process_id.strip():
        return jsonify({
            "success": False,
            "message": "Process ID is required"
        }), 400
    process_id = process_id.strip()

    if (
        not isinstance(resources, list)
        or not resources
        or any(not isinstance(resource, str) for resource in resources)
    ):
        return jsonify({
            "success": False,
            "message": "Provide a non-empty list of resource names"
        }), 400

    result = active_engine.allocate_resources(process_id, resources)

    if not result.get("success"):
        message = result.get("message", "Resource allocation failed")
        status_code = (
            404 if message == "Process not found"
            else 400 if (
                message.startswith("Unknown resource:")
                or "not selected as a required resource" in message
            )
            else 409
        )
        return jsonify({
            "success": False,
            "message": message,
            "process_id": process_id,
            "pending_requests": result.get("pending_requests", []),
            "available_resources": active_engine.resource_manager.get_all_resources()
        }), status_code

    return jsonify({
        "success": True,
        "process_id": process_id,
        "message": (
            f"{_format_resources(result.get('allocated', []))} allocated to "
            f"{process_id} successfully."
        ),
        "allocated_resources": result.get("allocated", []),
        "available_resources": result.get(
            "available", active_engine.resource_manager.get_all_resources()
        )
    }), 200

@app.route("/resources", methods=["GET"])
def resources():
    active_engine = engine
    return jsonify({
        "success": True,
        "resources": active_engine.resource_manager.get_all_resources()
    })


@app.route("/resource_capacity", methods=["GET", "PUT"])
def resource_capacity():
    if request.method == "GET":
        resource_manager = engine.resource_manager
        with resource_manager.lock:
            return jsonify({
                "success": True,
                "resources": resource_manager.get_all_resources(),
                "total_resources": (
                    resource_manager.get_total_resources()
                )
            })

    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400
    capacities = data.get("resource_capacity")
    if not isinstance(capacities, dict):
        return jsonify({
            "success": False,
            "message": "resource_capacity must be an object"
        }), 400
    if set(capacities) != set(engine.resource_order):
        return jsonify({
            "success": False,
            "message": "Provide a capacity for every supported resource"
        }), 400

    try:
        parsed_capacities = {
            resource: _parse_integer(
                capacities[resource], f"{resource} capacity"
            )
            for resource in engine.resource_order
        }
        result = engine.configure_resource_capacity(parsed_capacities)
    except (TypeError, ValueError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400

    return jsonify({
        "success": True,
        "message": "Resource capacities updated successfully.",
        "resources": result["available_resources"],
        "total_resources": result["total_resources"]
    })


def _format_resources(resources):
    quantities = {}
    for resource in resources:
        quantities[resource] = quantities.get(resource, 0) + 1
    return " and ".join(
        f"{name} × {quantity}" if quantity > 1 else name
        for name, quantity in quantities.items()
    )



@app.route("/release", methods=["POST"])
def release_resource():
    active_engine = engine
    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400

    process_id = data.get("process_id")

    if not isinstance(process_id, str) or not process_id.strip():
        return jsonify({
            "success": False,
            "message": "Process ID is required"
        }), 400
    process_id = process_id.strip()

    if active_engine.process_manager.get_process(process_id) is None:
        return jsonify({
            "success": False,
            "message": "Process not found"
        }), 404

    resource = data.get("resource")
    quantity = data.get("quantity")
    if resource is not None and not isinstance(resource, str):
        return jsonify({
            "success": False,
            "message": "Resource must be a string"
        }), 400
    if quantity is not None:
        try:
            quantity = _parse_integer(quantity, "Release quantity")
        except ValueError as error:
            return jsonify({
                "success": False,
                "message": str(error)
            }), 400

    result = active_engine.release_resources(process_id, resource, quantity)
    success = result["success"]

    return jsonify({
        "success": success,
        "process_id": process_id,
        "released_resources": result.get("released", []),
        "message": (
            (
                f"{_format_resources(result['released'])} released from "
                f"{process_id} successfully."
                if result.get("released")
                else f"No resources were released from {process_id}."
            )
            if success
            else result.get(
                "message",
                "No allocated resources found for this process"
            )
        ),
        "available_resources": active_engine.resource_manager.get_all_resources()
    }), 200 if success else 409


@app.route("/run_process", methods=["POST"])
def run_process():
    active_engine = engine
    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400

    process_id = data.get("process_id")

    if not isinstance(process_id, str) or not process_id.strip():
        return jsonify({
            "success": False,
            "message": "Process ID is required"
        }), 400
    process_id = process_id.strip()

    result = active_engine.run_process(process_id)

    if not result.get("success"):
        return jsonify(result), (
            404 if result.get("message") == "Process not found" else 409
        )

    return jsonify(result), 200

@app.route("/complete_process", methods=["POST"])
def complete_process():
    active_engine = engine
    data = _json_object()
    if data is None:
        return jsonify({
            "success": False,
            "message": "Request body must be a JSON object"
        }), 400

    process_id = data.get("process_id")

    if not isinstance(process_id, str) or not process_id.strip():
        return jsonify({
            "success": False,
            "message": "Process ID is required"
        }), 400
    process_id = process_id.strip()

    result = active_engine.complete_process(process_id)
    if not result["success"]:
        status_code = (
            404 if result["message"] == "Process not found" else 409
        )
        return jsonify(result), status_code
    return jsonify(result), 200

@app.route("/debug_resources")
def debug_resources():
    active_engine = engine
    rm = active_engine.resource_manager
    processes = active_engine.process_manager.get_all_processes()

    with rm.lock:
        available = rm.get_all_resources()
        allocated = {
            process_id: resources.copy()
            for process_id, resources in rm.allocated.items()
        }

    return jsonify({
        "available": available,
        "allocated": allocated,
        "process_states": {p.process_id: p.state for p in processes},
        "required_resources": {
            p.process_id: p.required_resources for p in processes
        }
    })







@app.route("/deadlock", methods=["GET"])
def deadlock():
    active_engine = engine
    try:
        result = active_engine.detect_current_deadlock()
    except (KeyError, TypeError, ValueError) as error:
        return jsonify({
            "success": False,
            "message": str(error)
        }), 400
    except Exception:
        app.logger.exception("Live deadlock detection failed")
        return jsonify({
            "success": False,
            "message": "Live deadlock detection failed"
        }), 500
    return jsonify({"success": True, **result})


@app.route("/system_status", methods=["GET"])
def system_status():
    active_engine = engine
    processes = active_engine.process_manager.get_all_processes()

    completed = 0
    running = 0
    new = 0

    for process in processes:
        if process.state == "COMPLETED":
            completed += 1
        elif process.state == "RUNNING":
            running += 1
        elif process.state == "NEW":
            new += 1

    return jsonify({
        "success": True,
        "total_processes": len(processes),
        "completed": completed,
        "running": running,
        "new": new,
        "resources":
            active_engine.resource_manager.get_all_resources()
    })


@app.route("/banker", methods=["POST"])
def banker_check():
    active_engine = engine
    data = _json_object()
    if data is None:
        if request.get_data(cache=True):
            return jsonify({
                "success": False,
                "message": "Request body must be a JSON object"
            }), 400
        data = {}
    if data:
        return jsonify({
            "success": False,
            "message": (
                "Banker's Algorithm uses live warehouse state; "
                "caller-supplied matrices are not accepted."
            )
        }), 400

    try:
        result = active_engine.check_current_warehouse_state()
    except Exception:
        app.logger.exception("Live Banker's Algorithm check failed")
        return jsonify({
            "success": False,
            "message": "Live Banker's Algorithm check failed"
        }), 500
    if result.get("error"):
        return jsonify({
            "success": False,
            "message": result["message"]
        }), 400

    return jsonify({
        "success": True,
        **result,
        "status": (
            "SAFE STATE"
            if result["safe"]
            else "UNSAFE STATE"
        ),
        "explanation": (
            "An unsafe Banker state does not by itself prove a current "
            "deadlock; see the live Deadlock Monitor."
        )
    })


    


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )