"""
Flask web wrapper for the last30days CLI research tool.
Serves a simple UI and runs the underlying script as a subprocess.
"""

import os
import subprocess
import sys
from pathlib import Path

import markdown
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

SCRIPT_PATH = Path(__file__).parent / "scripts" / "last30days.py"
RESEARCH_TIMEOUT = 300  # seconds
MAX_ERROR_LENGTH = 500


def _build_command(topic: str, depth: str, days: str, no_native_web: bool) -> list[str]:
    """Build the subprocess command from user inputs."""
    cmd = [sys.executable, str(SCRIPT_PATH), topic, "--emit=compact"]
    if depth == "quick":
        cmd.append("--quick")
    elif depth == "deep":
        cmd.append("--deep")
    if days and days.strip().isdigit():
        cmd.append(f"--days={days.strip()}")
    if no_native_web:
        cmd.append("--no-native-web")
    return cmd


def _get_param(key: str, default: str = "") -> str:
    """Get a parameter from either JSON body or form data."""
    if request.is_json:
        return str(request.json.get(key, default)).strip()
    return str(request.form.get(key, default)).strip()


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/research")
def research():
    topic = _get_param("topic")
    depth = _get_param("depth", "default")
    days = _get_param("days")
    no_native_web = bool(request.form.get("no_native_web") or (request.json.get("no_native_web", False) if request.is_json else False))

    if not topic:
        error = "A research topic is required."
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"error": error}), 400
        return render_template("index.html", error=error), 400

    if not os.environ.get("SCRAPECREATORS_API_KEY"):
        error = "SCRAPECREATORS_API_KEY environment variable is not set. Please configure it in your Render dashboard."
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"error": error}), 503
        return render_template("index.html", error=error, topic=topic), 503

    cmd = _build_command(topic, depth, days, no_native_web)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RESEARCH_TIMEOUT,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired:
        error = f"Research timed out after {RESEARCH_TIMEOUT} seconds. Try using --quick mode or a more specific topic."
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"error": error}), 504
        return render_template("index.html", error=error, topic=topic, depth=depth, days=days), 504
    except Exception as exc:  # noqa: BLE001
        error = f"Failed to start research process: {exc}"
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"error": error}), 500
        return render_template("index.html", error=error, topic=topic, depth=depth, days=days), 500

    if result.returncode != 0:
        stderr = result.stderr.strip()
        error = f"Research script exited with an error: {stderr[:MAX_ERROR_LENGTH] if stderr else 'unknown error'}"
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"error": error, "stderr": stderr}), 500
        return render_template("index.html", error=error, topic=topic, depth=depth, days=days), 500

    raw_output = result.stdout.strip()

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"topic": topic, "result": raw_output})

    html_output = markdown.markdown(raw_output, extensions=["nl2br", "fenced_code"])
    return render_template("index.html", topic=topic, depth=depth, days=days, result_html=html_output, result_raw=raw_output)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
