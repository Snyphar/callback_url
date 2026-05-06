import os
import urllib.parse
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

load_dotenv()

EXPECTED_TOKEN = "69973e1a9775aabc5379c5e1"

MONGO_URI = os.environ.get("MONGO_URI")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "otp_callback")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "callbacks")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable is required")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]
callbacks = db[MONGO_COLLECTION]

app = Flask(__name__)


def decode_otp(encoded_otp: str) -> str:
    # The OTP arrives URL-encoded; unquote restores the original value.
    return urllib.parse.unquote(encoded_otp) if encoded_otp else ""


@app.route("/callback", methods=["GET", "POST"])
def callback():
    pid = request.values.get("pid")
    encoded_otp = request.values.get("otp")
    token = request.values.get("token")

    if not pid or encoded_otp is None or not token:
        return jsonify({"status": "error", "message": "missing required parameters"}), 400

    if token != EXPECTED_TOKEN:
        return jsonify({"status": "error", "message": "invalid token"}), 401

    record = {
        "pid": pid,
        "encoded_otp": encoded_otp,
        "otp": decode_otp(encoded_otp),
        "token": token,
        "method": request.method,
        "remote_addr": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
        "query_string": request.query_string.decode("utf-8", errors="replace"),
        "full_url": request.url,
        "received_at": datetime.now(timezone.utc),
    }

    try:
        result = callbacks.insert_one(record)
    except PyMongoError as exc:
        return jsonify({"status": "error", "message": f"db error: {exc}"}), 500

    return jsonify({
        "status": "ok",
        "id": str(result.inserted_id),
        "pid": pid,
        "otp": record["otp"],
    }), 200


@app.route("/health", methods=["GET"])
def health():
    try:
        mongo_client.admin.command("ping")
        return jsonify({"status": "ok", "db": "connected"}), 200
    except PyMongoError as exc:
        return jsonify({"status": "error", "db": str(exc)}), 503


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
