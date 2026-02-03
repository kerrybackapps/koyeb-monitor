import os
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, render_template_string, Response

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KOYEB_API_BASE = "https://app.koyeb.com/v1"

message_log = []
logs_storage = {}  # Dict to store logs by app_name


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


def resolve_app_id(app_name):
    """Resolve an app name to a Koyeb app ID."""
    resp = requests.get(
        f"{KOYEB_API_BASE}/apps",
        headers=koyeb_headers(),
        params={"name": app_name},
    )
    resp.raise_for_status()
    apps = resp.json().get("apps", [])
    if not apps:
        return None, f"App '{app_name}' not found"
    return apps[0]["id"], None


def get_service_id(app_id):
    """Get the first service ID for an app."""
    resp = requests.get(
        f"{KOYEB_API_BASE}/services",
        headers=koyeb_headers(),
        params={"app_id": app_id},
    )
    resp.raise_for_status()
    services = resp.json().get("services", [])
    if not services:
        return None
    return services[0]["id"]


def fetch_koyeb_logs(service_id, limit=5000):
    """Fetch runtime logs from Koyeb's streaming logs API."""
    try:
        # Use the logs query endpoint
        resp = requests.get(
            f"{KOYEB_API_BASE}/streams/logs/query",
            headers=koyeb_headers(),
            params={
                "service_id": service_id,
                "type": "runtime",
                "limit": limit,
            },
            timeout=30,
        )
        resp.raise_for_status()

        logs_data = resp.json()
        logs_list = logs_data.get("logs", [])

        # Combine log messages into a single string
        log_lines = []
        for entry in logs_list:
            msg = entry.get("msg", "")
            if msg:
                log_lines.append(msg)

        return "\n".join(log_lines)
    except Exception as e:
        logger.error(f"Failed to fetch logs from Koyeb: {e}")
        return f"[Error fetching logs: {e}]"


def delete_app(app_id):
    """Delete a Koyeb app by ID."""
    resp = requests.delete(
        f"{KOYEB_API_BASE}/apps/{app_id}",
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

    app_name = data.get("app_name")

    if not app_name:
        return jsonify({"error": "app_name is required"}), 400

    logger.info(f"Kill requested for app: {app_name}")
    log_message("received", "/kill", data)

    # Resolve app name to ID
    app_id, error = resolve_app_id(app_name)
    if error:
        logger.error(f"Failed to resolve app: {error}")
        response = {"status": "error", "app_name": app_name, "message": error}
        log_message("sent", "/kill", response, status=404)
        return jsonify(response), 404

    # Delete the app
    try:
        delete_app(app_id)
        logger.info(f"Successfully deleted app: {app_name} (id: {app_id})")
        response = {
            "status": "deleted",
            "app_name": app_name,
            "app_id": app_id,
        }
        log_message("sent", "/kill", response, status=200)
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Failed to delete app {app_name}: {e}")
        response = {"status": "error", "app_name": app_name, "message": str(e)}
        log_message("sent", "/kill", response, status=500)
        return jsonify(response), 500


@app.route("/init-logs", methods=["POST"])
def init_logs():
    """Initialize log entry when a service first starts.

    Creates the log file immediately so the logs link is active right away,
    before waiting for the first periodic /submit-logs update.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    app_name = data.get("app_name")
    if not app_name:
        return jsonify({"error": "app_name is required"}), 400

    model = data.get("model", "unknown")
    start = data.get("start", "?")
    end = data.get("end", "?")
    instance_type = data.get("instance_type", "unknown")
    started_at = data.get("started_at", datetime.now(timezone.utc).isoformat())

    logger.info(f"Init logs for app: {app_name} (model={model}, {start}-{end}, {instance_type})")
    log_message("received", "/init-logs", data)

    init_text = (
        f"Service starting: {model} indices {start}-{int(end)-1} on {instance_type}\n"
        f"App: {app_name}\n"
        f"Started at: {started_at}\n"
        f"\nWaiting for logs...\n"
    )

    logs_storage[app_name] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logs": init_text,
        "source": "init",
    }

    response = {"status": "initialized", "app_name": app_name}
    log_message("sent", "/init-logs", response, status=200)
    return jsonify(response), 200


@app.route("/submit-logs", methods=["POST"])
def submit_logs():
    """Receive and store logs from a running app before it terminates."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    app_name = data.get("app_name")
    logs = data.get("logs")

    if not app_name:
        return jsonify({"error": "app_name is required"}), 400
    if logs is None:
        return jsonify({"error": "logs field is required"}), 400

    logger.info(f"Logs received for app: {app_name} ({len(logs)} chars)")
    log_message("received", "/submit-logs", {"app_name": app_name, "logs_length": len(logs)})

    logs_storage[app_name] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logs": logs,
    }

    response = {"status": "stored", "app_name": app_name}
    log_message("sent", "/submit-logs", response, status=200)
    return jsonify(response), 200


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


LOGS_LIST_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Koyeb Monitor - Run Logs</title>
    <style>
        body { font-family: monospace; margin: 2em; background: #1a1a2e; color: #eee; }
        h1 { color: #4fc3f7; }
        .count { color: #aaa; margin-top: 0.5em; }
        ul { list-style: none; padding: 0; }
        li { margin: 0.5em 0; padding: 0.5em; background: #16213e; border-radius: 4px; }
        a { color: #81c784; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .timestamp { color: #aaa; font-size: 0.85em; margin-left: 1em; }
        .source { color: #ffb74d; font-size: 0.85em; margin-left: 0.5em; }
        .no-logs { color: #e57373; }
    </style>
</head>
<body>
    <h1>Koyeb Monitor - Run Logs</h1>
    <p class="count">{{ count }} app log(s) stored</p>
    {% if logs %}
    <ul>
        {% for app_name, entry in logs.items() %}
        <li>
            <a href="/logs/{{ app_name }}">{{ app_name }}</a>
            <span class="timestamp">{{ entry.timestamp }}</span>
            {% if entry.source == 'koyeb_api' %}<span class="source">[fetched]</span>{% endif %}
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <p class="no-logs">No logs stored yet.</p>
    {% endif %}
</body>
</html>
"""

LOGS_VIEW_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Logs - {{ app_name }}</title>
    <style>
        body { font-family: monospace; margin: 2em; background: #1a1a2e; color: #eee; }
        h1 { color: #4fc3f7; }
        .meta { color: #aaa; margin-bottom: 1em; }
        a { color: #81c784; }
        pre {
            background: #0f3460;
            padding: 1em;
            border-radius: 4px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
    </style>
</head>
<body>
    <h1>{{ app_name }}</h1>
    <p class="meta">Captured: {{ timestamp }}{% if source %} | Source: {{ source }}{% endif %} | <a href="/">Back to list</a></p>
    <pre>{{ logs|e }}</pre>
</body>
</html>
"""


@app.route("/", methods=["GET"])
@app.route("/logs", methods=["GET"])
def logs_list():
    """List all stored app logs."""
    return render_template_string(
        LOGS_LIST_TEMPLATE, logs=logs_storage, count=len(logs_storage)
    )


@app.route("/logs/<app_name>", methods=["GET"])
def logs_view(app_name):
    """View logs for a specific app."""
    if app_name not in logs_storage:
        return render_template_string(
            """
            <!DOCTYPE html>
            <html>
            <head><title>Not Found</title>
            <style>body { font-family: monospace; margin: 2em; background: #1a1a2e; color: #eee; }
            a { color: #81c784; }</style></head>
            <body><h1>Logs not found for: {{ app_name }}</h1>
            <p><a href="/">Back to list</a></p></body>
            </html>
            """,
            app_name=app_name,
        ), 404
    entry = logs_storage[app_name]
    return render_template_string(
        LOGS_VIEW_TEMPLATE,
        app_name=app_name,
        timestamp=entry["timestamp"],
        logs=entry["logs"],
        source=entry.get("source", "submitted"),
    )


@app.route("/logs-raw/<app_name>", methods=["GET"])
def logs_raw(app_name):
    """Return raw logs as plain text (no HTML rendering)."""
    if app_name not in logs_storage:
        return f"No logs found for: {app_name}\n", 404, {"Content-Type": "text/plain"}
    entry = logs_storage[app_name]
    return Response(entry["logs"], mimetype="text/plain")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
