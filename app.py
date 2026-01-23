import os
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KOYEB_API_BASE = "https://app.koyeb.com/v1"

message_log = []


def log_message(direction, endpoint, data, status=None):
    """Record a message to the in-memory log.

    direction: 'received' or 'sent'
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "endpoint": endpoint,
        "data": data,
    }
    if status is not None:
        entry["status"] = status
    message_log.append(entry)


def get_api_token():
    token = os.environ.get("KOYEB_API_TOKEN")
    if not token:
        raise RuntimeError("KOYEB_API_TOKEN environment variable not set")
    return token


def koyeb_headers():
    return {
        "Authorization": f"Bearer {get_api_token()}",
        "Content-Type": "application/json",
    }


def resolve_service_id(service_name, app_name):
    """Resolve a service name + app name to a Koyeb service ID."""
    resp = requests.get(
        f"{KOYEB_API_BASE}/apps",
        headers=koyeb_headers(),
        params={"name": app_name},
    )
    resp.raise_for_status()
    apps = resp.json().get("apps", [])
    if not apps:
        return None, f"App '{app_name}' not found"
    app_id = apps[0]["id"]

    resp = requests.get(
        f"{KOYEB_API_BASE}/services",
        headers=koyeb_headers(),
        params={"app_id": app_id, "name": service_name},
    )
    resp.raise_for_status()
    services = resp.json().get("services", [])
    if not services:
        return None, f"Service '{service_name}' not found in app '{app_name}'"
    return services[0]["id"], None


def delete_service(service_id):
    """Delete a Koyeb service by ID."""
    resp = requests.delete(
        f"{KOYEB_API_BASE}/services/{service_id}",
        headers=koyeb_headers(),
    )
    resp.raise_for_status()
    return resp.json()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    service_name = data.get("service_name")
    app_name = data.get("app_name")

    if not service_name or not app_name:
        return jsonify({"error": "service_name and app_name are required"}), 400

    logger.info(f"Service registered: {service_name} (app: {app_name})")
    log_message("received", "/register", data)
    response = {
        "status": "registered",
        "service_name": service_name,
        "app_name": app_name,
    }
    log_message("sent", "/register", response, status=200)
    return jsonify(response), 200


@app.route("/kill", methods=["POST"])
def kill():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    service_name = data.get("service_name")
    app_name = data.get("app_name")

    if not service_name or not app_name:
        return jsonify({"error": "service_name and app_name are required"}), 400

    logger.info(f"Kill requested for service: {service_name} (app: {app_name})")
    log_message("received", "/kill", data)

    try:
        service_id, err = resolve_service_id(service_name, app_name)
        if err:
            logger.error(f"Failed to resolve service: {err}")
            response = {"error": err}
            log_message("sent", "/kill", response, status=404)
            return jsonify(response), 404

        result = delete_service(service_id)
        logger.info(f"Service '{service_name}' deleted successfully")
        response = {
            "status": "killed",
            "service_name": service_name,
            "app_name": app_name,
            "service_id": service_id,
        }
        log_message("sent", "/kill", response, status=200)
        return jsonify(response), 200
    except requests.exceptions.HTTPError as e:
        logger.error(f"Koyeb API error: {e.response.text}")
        response = {"error": f"Koyeb API error: {e.response.status_code}"}
        log_message("sent", "/kill", response, status=502)
        return jsonify(response), 502
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        response = {"error": str(e)}
        log_message("sent", "/kill", response, status=500)
        return jsonify(response), 500


MESSAGES_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Koyeb Monitor - Messages</title>
    <style>
        body { font-family: monospace; margin: 2em; background: #1a1a2e; color: #eee; }
        h1 { color: #0f3460; }
        table { border-collapse: collapse; width: 100%; margin-top: 1em; }
        th, td { border: 1px solid #444; padding: 8px; text-align: left; }
        th { background: #16213e; }
        tr:nth-child(even) { background: #0f3460; }
        .received { color: #4fc3f7; }
        .sent { color: #81c784; }
        .status-200 { color: #81c784; }
        .status-404, .status-500, .status-502 { color: #e57373; }
        .count { color: #aaa; margin-top: 0.5em; }
        pre { margin: 0; white-space: pre-wrap; font-size: 0.85em; }
    </style>
</head>
<body>
    <h1>Koyeb Monitor - Message Log</h1>
    <p class="count">{{ count }} message(s)</p>
    <table>
        <tr>
            <th>Time (UTC)</th>
            <th>Direction</th>
            <th>Endpoint</th>
            <th>Status</th>
            <th>Data</th>
        </tr>
        {% for msg in messages %}
        <tr>
            <td>{{ msg.timestamp }}</td>
            <td class="{{ msg.direction }}">{{ msg.direction }}</td>
            <td>{{ msg.endpoint }}</td>
            <td class="status-{{ msg.status or '' }}">{{ msg.status or '-' }}</td>
            <td><pre>{{ msg.data | tojson(indent=2) }}</pre></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""


@app.route("/messages", methods=["GET"])
def messages():
    """View all received and sent messages as an HTML page."""
    return render_template_string(
        MESSAGES_TEMPLATE, messages=message_log, count=len(message_log)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
