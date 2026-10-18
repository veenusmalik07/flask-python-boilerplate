from flask import Blueprint, request, jsonify
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

api_bp = Blueprint("api", __name__)

@api_bp.post("/api/answer")
def answer_question():
    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()

    if not question:
        return jsonify({"error": "A question is required"}), 400

    return jsonify({
        "error": (
            "Ledger data and question-answering logic "
            "have not been configured yet."
        )
    }), 501
