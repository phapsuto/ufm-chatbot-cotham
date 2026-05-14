"""app/services/handoff_service.py — Lưu lead học viên cần tư vấn"""
import csv
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path

from app.models import HandoffRequest

logger = logging.getLogger("ufm-chatbot")

DATA_DIR = Path("data")
LEADS_CSV = DATA_DIR / "handoff_leads.csv"
LEADS_JSON = DATA_DIR / "handoff_leads.json"


def _ensure_csv():
    if not LEADS_CSV.exists():
        with open(LEADS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "timestamp", "name", "phone", "email", "interest", "session_id", "transcript_summary"])


async def save_lead(data: HandoffRequest, transcript: list[dict]) -> bool:
    try:
        _ensure_csv()
        lead_id = str(uuid.uuid4())[:8]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        summary = " | ".join([f"{m['role']}: {m['content'][:80]}" for m in transcript[-5:]])

        # CSV
        with open(LEADS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([lead_id, ts, data.name, data.phone, data.email, data.interest, data.session_id, summary])

        # JSON
        record = {
            "id": lead_id, "timestamp": ts, "name": data.name,
            "phone": data.phone, "email": data.email, "interest": data.interest,
            "session_id": data.session_id, "transcript_summary": summary,
        }
        existing = []
        if LEADS_JSON.exists():
            with open(LEADS_JSON, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(record)
        with open(LEADS_JSON, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        logger.info(f"[handoff] lead saved name={data.name} phone={data.phone}")
        return True
    except Exception as e:
        logger.error(f"[handoff] ERROR saving lead: {e}")
        return False
