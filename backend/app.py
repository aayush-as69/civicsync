"""CivicSync Flask API — local-first civic maintenance prototype."""
from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from pathlib import Path
from functools import wraps
from importlib.util import find_spec
from typing import Any

from flask import Flask, current_app, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy import func, text as sql_text
from sqlalchemy.exc import IntegrityError


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

VALID_CATEGORIES = [
    "Road Damage", "Streetlight", "Garbage", "Water Leakage", "Blocked Drain",
    "Public Property", "General Review",
]
VALID_URGENCY = ["Low", "Medium", "High", "Critical"]
VALID_STATUSES = ["Submitted", "Under Review", "Assigned", "In Progress", "Resolved", "Rejected", "Cancelled"]
TRANSITIONS = {
    "Submitted": {"Under Review", "Assigned", "Cancelled", "Rejected"},
    "Under Review": {"Assigned", "Rejected", "Cancelled"},
    "Assigned": {"In Progress", "Under Review", "Cancelled"},
    "In Progress": {"Resolved", "Assigned", "Cancelled"},
    "Resolved": set(), "Rejected": set(), "Cancelled": set(),
}

db = SQLAlchemy()


def now() -> datetime:
    return datetime.now(timezone.utc)


class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(60), unique=True, nullable=False)
    description = db.Column(db.String(240), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140))
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(60), nullable=False)
    summary = db.Column(db.String(280), nullable=False)
    location = db.Column(db.String(220), nullable=False)
    area_details = db.Column(db.String(220))
    urgency = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    analysis_provider = db.Column(db.String(30), nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    idempotency_key = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)
    ticket = db.relationship("Ticket", back_populates="complaint", uselist=False, cascade="all, delete-orphan")


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(32), unique=True, nullable=False, index=True)
    tracking_token = db.Column(db.String(64), unique=True, nullable=False)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaint.id"), nullable=False, unique=True)
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"), nullable=False, index=True)
    status = db.Column(db.String(30), default="Submitted", nullable=False, index=True)
    internal_note = db.Column(db.Text)
    resolution_summary = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    resolved_at = db.Column(db.DateTime(timezone=True))
    complaint = db.relationship("Complaint", back_populates="ticket")
    department = db.relationship("Department")
    history = db.relationship("StatusHistory", back_populates="ticket", cascade="all, delete-orphan", order_by="StatusHistory.created_at")


class StatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"), nullable=False, index=True)
    from_status = db.Column(db.String(30))
    to_status = db.Column(db.String(30), nullable=False)
    actor = db.Column(db.String(100), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    ticket = db.relationship("Ticket", back_populates="history")


class AgentEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_reference = db.Column(db.String(32), index=True)
    stage = db.Column(db.String(80), nullable=False)
    agent = db.Column(db.String(80), nullable=False)
    outcome = db.Column(db.String(20), nullable=False)
    detail = db.Column(db.String(360), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default="Local")
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False, index=True)


def api_error(message: str, status: int = 400, code: str = "validation_error", details: dict | None = None):
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def event(stage: str, agent: str, outcome: str, detail: str, ticket_reference: str | None = None):
    db.session.add(AgentEvent(stage=stage, agent=agent, outcome=outcome, detail=detail, ticket_reference=ticket_reference))


def text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


class AnalysisAgent:
    """Structured Gemini analysis with deterministic, explicitly labelled fallback."""
    patterns = [
        ("Blocked Drain", ["drain", "sewer", "clog", "blocked drain", "flood"]),
        ("Water Leakage", ["leak", "water pipe", "water tap", "burst pipe"]),
        ("Streetlight", ["streetlight", "street light", "lamp post", "lamp"]),
        ("Garbage", ["garbage", "trash", "waste", "overflowing bin", "rubbish"]),
        ("Road Damage", ["pothole", "road damage", "broken road", "crater", "damaged road"]),
        ("Public Property", ["bench", "park", "public property", "bus stop", "signboard"]),
    ]

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        description = text(payload.get("description"), 2000)
        supplied_category = text(payload.get("category"), 60)
        location = text(payload.get("location"), 220)
        if not description:
            raise ValueError("A complaint description is required.")
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if key:
            try:
                result = self._gemini(payload, key)
                result["provider"] = "gemini"
                result["location"] = location or result.get("location") or None
                result["missing_fields"] = self._missing_fields(description, result.get("location") or "")
                result["suggested_department"] = self._department_name(result["category"])
                return result
            except Exception:
                # Never pretend Gemini succeeded; retain service availability with a clear fallback label.
                pass
        return self._fallback(payload, description, supplied_category, location)

    @staticmethod
    def _missing_fields(description: str, location: str) -> list[str]:
        missing = []
        if not location:
            missing.append("location")
        if len(description.strip()) < 12:
            missing.append("description detail")
        return missing

    @staticmethod
    def _department_name(category: str) -> str:
        names = {
            "Road Damage": "Road Maintenance",
            "Streetlight": "Electrical Maintenance",
            "Garbage": "Sanitation",
            "Water Leakage": "Water Supply",
            "Blocked Drain": "Drainage Department",
            "Public Property": "Public Works",
            "General Review": "General Review Queue",
        }
        return names.get(category, "General Review Queue")

    def _gemini(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        model = re.sub(r"[^A-Za-z0-9._-]", "", os.getenv("GEMINI_MODEL", "gemini-2.5-flash")) or "gemini-2.5-flash"
        prompt = {
            "task": "Classify a civic maintenance complaint. Return only JSON matching the schema.",
            "allowed_categories": VALID_CATEGORIES,
            "allowed_urgency": VALID_URGENCY,
            "fields": {"category": "one allowed category", "summary": "short factual summary, max 140 chars", "urgency": "one allowed urgency", "suggested_department": "department name", "confidence": "number from 0 to 1"},
            "complaint": {"title": text(payload.get("title"), 140), "description": text(payload.get("description"), 2000), "location": text(payload.get("location"), 220), "category_hint": text(payload.get("category"), 60), "urgency_hint": text(payload.get("urgency"), 20)},
            "rules": ["Do not invent facts", "Use General Review when uncertain", "Critical only for immediate serious safety risk", "Confidence must be between 0 and 1"],
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
        req = Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
        with urlopen(req, timeout=8) as response:
            raw = json.loads(response.read().decode("utf-8"))
        candidate_text = raw["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(candidate_text)
        category = result.get("category")
        urgency = result.get("urgency")
        if category not in VALID_CATEGORIES or urgency not in VALID_URGENCY:
            raise ValueError("Gemini returned an unsupported category or urgency.")
        confidence = float(result.get("confidence", 0.5))
        if not 0 <= confidence <= 1:
            raise ValueError("Gemini returned invalid confidence.")
        summary = text(result.get("summary"), 140) or text(payload.get("title"), 140) or text(payload.get("description"), 140)
        suggested = text(result.get("suggested_department"), 100) or "General Review Queue"
        return {"category": category, "summary": summary, "location": text(payload.get("location"), 220) or None, "urgency": urgency, "suggested_department": suggested, "missing_fields": [], "confidence": confidence}

    def _fallback(self, payload: dict[str, Any], description: str, supplied_category: str, location: str) -> dict[str, Any]:
        lowered = description.lower()
        category = supplied_category if supplied_category in VALID_CATEGORIES[:-1] else "General Review"
        if category == "General Review":
            for candidate, terms in self.patterns:
                if any(term in lowered for term in terms):
                    category = candidate
                    break
        urgency = text(payload.get("urgency"), 20)
        if urgency not in VALID_URGENCY:
            urgency = "Critical" if any(x in lowered for x in ["danger", "accident", "fire", "electrical shock"]) else "High" if any(x in lowered for x in ["school", "hospital", "heavy", "three days"]) else "Medium"
        summary = text(payload.get("title"), 140) or re.sub(r"\s+", " ", description)[:140]
        suggested = self._department_name(category)
        confidence = 0.88 if category != "General Review" else 0.42
        return {"category": category, "summary": summary, "location": location or None, "urgency": urgency, "suggested_department": suggested, "missing_fields": self._missing_fields(description, location), "confidence": confidence, "provider": "local-fallback"}


class RoutingAgent:
    def route(self, analysis: dict[str, Any]) -> Department:
        department = Department.query.filter_by(category=analysis["category"], active=True).first()
        return department or Department.query.filter_by(category="General Review", active=True).first()


analysis_agent = AnalysisAgent()
routing_agent = RoutingAgent()


def validate_analysis(result: dict[str, Any]) -> None:
    if result.get("category") not in VALID_CATEGORIES or result.get("urgency") not in VALID_URGENCY:
        raise ValueError("Analysis output did not match the permitted civic-service schema.")
    if (not isinstance(result.get("missing_fields"), list)
            or not all(isinstance(item, str) for item in result.get("missing_fields", []))
            or not isinstance(result.get("confidence"), (int, float))
            or not 0 <= float(result.get("confidence", -1)) <= 1
            or not text(result.get("summary"), 140)):
        raise ValueError("Analysis output is malformed.")


def ticket_payload(ticket: Ticket, include_token: bool = False, include_private: bool = False) -> dict[str, Any]:
    complaint = ticket.complaint
    data = {
        "ticket_id": ticket.reference, "title": complaint.title, "summary": complaint.summary,
        "description": complaint.description, "category": complaint.category, "location": complaint.location,
        "area_details": complaint.area_details, "urgency": complaint.urgency, "confidence": complaint.confidence,
        "analysis_provider": complaint.analysis_provider, "department": ticket.department.name,
        "status": ticket.status, "resolution_summary": ticket.resolution_summary,
        "is_demo": complaint.is_demo, "submitted_at": iso(complaint.created_at), "updated_at": iso(ticket.updated_at),
        "resolved_at": iso(ticket.resolved_at),
        "history": [{"from": h.from_status, "to": h.to_status, "actor": h.actor, "note": h.note if include_private else None, "at": iso(h.created_at)} for h in ticket.history],
    }
    if include_private:
        data["internal_note"] = ticket.internal_note
    if include_token:
        data["tracking_token"] = ticket.tracking_token
    return data


def is_admin_request(app: Flask) -> bool:
    configured_token = os.getenv("ADMIN_API_TOKEN", "").strip()
    bearer = request.headers.get("Authorization", "")
    if configured_token and bearer.startswith("Bearer ") and secrets.compare_digest(bearer[7:], configured_token):
        return True
    return bool(app.config.get("DEMO_MODE") and app.config.get("ALLOW_DEMO_ADMIN_HEADER") and request.headers.get("X-Demo-Role") == "admin")


def require_admin(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not is_admin_request(current_app):
            return api_error("Administrator authentication is required.", 401, "unauthorized")
        return handler(*args, **kwargs)
    return wrapped


def seed_data():
    if Department.query.count() == 0:
        rows = [
            ("Road Maintenance", "Road Damage", "Potholes, roads, footpaths and surface defects."),
            ("Electrical Maintenance", "Streetlight", "Streetlight and municipal electrical faults."),
            ("Sanitation", "Garbage", "Waste collection and public sanitation."),
            ("Water Supply", "Water Leakage", "Leaks, taps and water-supply infrastructure."),
            ("Drainage Department", "Blocked Drain", "Drains, sewers and storm-water flows."),
            ("Public Works", "Public Property", "Damaged public amenities and fixtures."),
            ("General Review Queue", "General Review", "Human review for ambiguous civic reports."),
        ]
        db.session.add_all([Department(name=n, category=c, description=d) for n, c, d in rows])
        db.session.commit()
    if Complaint.query.filter_by(is_demo=True).count():
        return
    samples = [
        ("Pothole near college entrance", "A deep pothole is forming outside the campus main gate.", "Road Damage", "College main gate", "High", "In Progress"),
        ("Walkway streetlight not working", "The streetlight beside the public walkway has been off for three days.", "Streetlight", "Public walkway", "Medium", "Assigned"),
        ("Overflowing garbage bin", "Garbage is overflowing beside the residential building.", "Garbage", "Greenview Apartments", "Medium", "Submitted"),
        ("Leak at public tap", "Water is leaking continuously near the public tap.", "Water Leakage", "Community tap on Lake Road", "High", "Resolved"),
        ("Rainwater drain blocked", "The drain is blocked after heavy rain and water is collecting.", "Blocked Drain", "Market lane", "High", "Under Review"),
        ("Unclear civic issue", "Something is damaged and needs attention.", "General Review", "Town square", "Low", "Submitted"),
    ]
    for ix, (title, desc, cat, location, urgency, status) in enumerate(samples, 1):
        complaint = Complaint(title=title, description=desc, category=cat, summary=title, location=location, urgency=urgency, confidence=.91 if cat != "General Review" else .4, analysis_provider="seed-data", is_demo=True)
        department = Department.query.filter_by(category=cat).first()
        ticket = Ticket(reference=f"CS-DEMO-{ix:03d}", tracking_token=secrets.token_urlsafe(24), complaint=complaint, department=department, status=status)
        if status == "Resolved": ticket.resolved_at = now(); ticket.resolution_summary = "Demo resolution recorded."
        db.session.add(ticket)
        db.session.flush()
        db.session.add(StatusHistory(ticket_id=ticket.id, from_status=None, to_status="Submitted", actor="demo-seed", note="Controlled demo record"))
        if status != "Submitted": db.session.add(StatusHistory(ticket_id=ticket.id, from_status="Submitted", to_status=status, actor="demo-admin", note="Demo status update"))
    db.session.commit()


def default_database_url() -> str:
    """Resolve the DB URL. On Vercel the filesystem is read-only except /tmp, and /tmp is
    ephemeral, so SQLite there is demo-only; set DATABASE_URL to Postgres for persistence."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url:
        return url
    if os.getenv("VERCEL"):
        return "sqlite:////tmp/civicsync.db"
    return "sqlite:///civicsync.db"


def create_app(test_config: dict | None = None):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=default_database_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=os.getenv("SECRET_KEY", "development-only-change-me"),
        DEMO_MODE=os.getenv("DEMO_MODE", "false").lower() == "true",
        ALLOW_DEMO_ADMIN_HEADER=os.getenv("ALLOW_DEMO_ADMIN_HEADER", "").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)
    if os.getenv("APP_ENV", os.getenv("FLASK_ENV", "")).lower() == "production":
        secret = str(app.config.get("SECRET_KEY", ""))
        if len(secret) < 32 or secret == "development-only-change-me":
            raise RuntimeError("Production requires a strong SECRET_KEY of at least 32 characters.")
        if app.config["DEMO_MODE"]:
            raise RuntimeError("DEMO_MODE must be false in production.")
        if app.config["ALLOW_DEMO_ADMIN_HEADER"]:
            raise RuntimeError("ALLOW_DEMO_ADMIN_HEADER must be false in production.")
    # A comma-separated allowlist permits local Vite to be reached through either
    # localhost or 127.0.0.1 without opening CORS to arbitrary browser origins.
    frontend_origins = [origin.strip() for origin in os.getenv("FRONTEND_URL", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
    CORS(app, resources={r"/api/*": {"origins": frontend_origins}})
    db.init_app(app)
    with app.app_context():
        db.create_all()
        if app.config["DEMO_MODE"]:
            seed_data()

    @app.get("/api/health")
    def health():
        uagents_enabled = os.getenv("UAGENTS_ENABLED", "false").lower() == "true"
        uagents_status = "disabled" if not uagents_enabled else ("configured-unverified" if find_spec("uagents") else "dependency-unavailable")
        try:
            db.session.execute(sql_text("SELECT 1"))
            database_status = "ready"
        except Exception:
            db.session.rollback()
            database_status = "unavailable"
        analysis_status = "gemini-configured-unverified-fallback-enabled" if os.getenv("GEMINI_API_KEY") else "local-fallback"
        status = "ok" if database_status == "ready" else "degraded"
        return jsonify({"status": status, "database": database_status, "analysis": analysis_status, "uagents": uagents_status, "demo_mode": app.config["DEMO_MODE"]}), (200 if database_status == "ready" else 503)

    @app.get("/api/departments")
    def departments():
        return jsonify({"data": [{"name": d.name, "category": d.category, "description": d.description} for d in Department.query.filter_by(active=True).order_by(Department.name)]})

    @app.post("/api/complaints/analyze")
    def analyze_complaint():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("JSON body must be an object.", 400, "invalid_json_body")
        try:
            result = analysis_agent.analyze(payload); validate_analysis(result)
            return jsonify({"data": result})
        except ValueError as exc:
            return api_error(str(exc))

    @app.post("/api/complaints")
    def create_complaint():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("JSON body must be an object.", 400, "invalid_json_body")
        raw_key = request.headers.get("Idempotency-Key", "")
        if len(raw_key) > 100:
            return api_error("Idempotency-Key must be at most 100 characters.", 400, "invalid_idempotency_key")
        key = raw_key.strip() or None
        if key:
            existing = Complaint.query.filter_by(idempotency_key=key).first()
            if existing:
                return jsonify({"data": ticket_payload(existing.ticket, False), "idempotent_replay": True, "message": "Submission already exists. The tracking token is not repeated on replay."}), 200
        try:
            event("Complaint received", "User Interface Agent", "success", "Basic request validation passed.")
            result = analysis_agent.analyze(payload); validate_analysis(result)
            event("Analysis completed", "Analysis Agent", "success", f"Structured by {result['provider']}.")
            event("Output validated", "User Interface Agent", "success", "Schema and permitted values accepted.")
            if result["missing_fields"]:
                event("Needs clarification", "Analysis Agent", "blocked", "Missing: " + ", ".join(result["missing_fields"]))
                db.session.commit()
                return api_error("We need a little more information before creating a ticket.", 422, "missing_information", {"missing_fields": result["missing_fields"], "analysis": result})
            department = routing_agent.route(result)
            if not department:
                raise ValueError("No eligible department is configured.")
            event("Department selected", "Routing Agent", "success", department.name)
            complaint = Complaint(title=text(payload.get("title"), 140) or None, description=text(payload.get("description"), 2000), category=result["category"], summary=result["summary"], location=result["location"], area_details=text(payload.get("area_details"), 220) or None, urgency=result["urgency"], confidence=result["confidence"], analysis_provider=result["provider"], idempotency_key=key)
            reference = f"CS-{now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
            ticket = Ticket(reference=reference, tracking_token=secrets.token_urlsafe(24), complaint=complaint, department=department, status="Submitted")
            db.session.add(ticket); db.session.flush()
            db.session.add(StatusHistory(ticket_id=ticket.id, from_status=None, to_status="Submitted", actor="citizen", note="Ticket created through local workflow"))
            event("Ticket created", "Routing Agent", "success", "Persistent ticket successfully created.", reference)
            db.session.commit()
            return jsonify({"data": ticket_payload(ticket, True)}), 201
        except IntegrityError:
            db.session.rollback()
            # Concurrent requests may race between the initial idempotency lookup and commit.
            if key:
                existing = Complaint.query.filter_by(idempotency_key=key).first()
                if existing and existing.ticket:
                    return jsonify({
                        "data": ticket_payload(existing.ticket, include_token=False),
                        "idempotent_replay": True,
                        "message": "Submission already exists. The tracking token is not repeated on replay.",
                    }), 200
            return api_error("The submission conflicted with an existing record. Retry using the same idempotency key.", 409, "duplicate_submission")
        except ValueError as exc:
            db.session.rollback(); return api_error(str(exc), 422, "workflow_error")
        except Exception:
            db.session.rollback(); return api_error("The workflow could not complete. No ticket was created.", 500, "workflow_failed")

    @app.get("/api/tickets/<reference>")
    def get_ticket(reference: str):
        ticket = Ticket.query.filter_by(reference=reference.upper()).first()
        if not ticket:
            return api_error("Ticket not found.", 404, "not_found")
        is_admin = is_admin_request(app)
        if not is_admin and not secrets.compare_digest(request.headers.get("X-Tracking-Token", ""), ticket.tracking_token):
            return api_error("A matching tracking token is required for this ticket.", 403, "ticket_access_denied")
        return jsonify({"data": ticket_payload(ticket, include_token=False, include_private=is_admin)})

    @app.get("/api/tickets")
    @require_admin
    def list_tickets():
        query = Ticket.query.join(Complaint).join(Department)
        filters = {"status": Ticket.status, "department": Department.name, "category": Complaint.category, "urgency": Complaint.urgency}
        for name, column in filters.items():
            if request.args.get(name): query = query.filter(column == request.args[name])
        search = text(request.args.get("q"), 100)
        if search: query = query.filter((Ticket.reference.ilike(f"%{search}%")) | (Complaint.summary.ilike(f"%{search}%")))
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
        except (TypeError, ValueError):
            return api_error("page and per_page must be integers.", 400, "invalid_pagination")
        if page < 1 or per_page < 1 or per_page > 100:
            return api_error("page must be >= 1 and per_page must be between 1 and 100.", 400, "invalid_pagination")
        paged = query.order_by(Ticket.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({"data": [ticket_payload(t, include_private=True) for t in paged.items], "meta": {"page": page, "per_page": per_page, "total": paged.total}})

    @app.patch("/api/tickets/<reference>/status")
    @require_admin
    def update_ticket(reference: str):
        ticket = Ticket.query.filter_by(reference=reference.upper()).first()
        if not ticket: return api_error("Ticket not found.", 404, "not_found")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("JSON body must be an object.", 400, "invalid_json_body")
        target = text(payload.get("status"), 30)
        if target not in VALID_STATUSES: return api_error("Unsupported ticket status.")
        if target not in TRANSITIONS.get(ticket.status, set()): return api_error(f"{ticket.status} cannot transition to {target}.", 422, "invalid_transition")
        resolution_summary = text(payload.get("resolution_summary"), 2000)
        if target == "Resolved" and not (resolution_summary or ticket.resolution_summary):
            return api_error("A resolution summary is required before resolving a ticket.", 422, "resolution_summary_required")
        previous = ticket.status; ticket.status = target; ticket.updated_at = now()
        ticket.internal_note = text(payload.get("internal_note"), 2000) or ticket.internal_note
        if target == "Resolved":
            ticket.resolved_at = now()
            ticket.resolution_summary = resolution_summary or ticket.resolution_summary
        db.session.add(StatusHistory(ticket_id=ticket.id, from_status=previous, to_status=target, actor="demo-admin" if app.config["DEMO_MODE"] else "admin", note=text(payload.get("note"), 1000) or None))
        db.session.commit()
        return jsonify({"data": ticket_payload(ticket, include_private=True)})

    @app.get("/api/dashboard/summary")
    @require_admin
    def dashboard_summary():
        tickets = Ticket.query.all(); total = len(tickets)
        status_counts = Counter(t.status for t in tickets); category_counts = Counter(t.complaint.category for t in tickets); dept_counts = Counter(t.department.name for t in tickets)
        recent = Ticket.query.order_by(Ticket.updated_at.desc()).limit(6).all()
        return jsonify({"data": {"total": total, "submitted": status_counts["Submitted"], "under_review": status_counts["Under Review"], "in_progress": status_counts["In Progress"], "resolved": status_counts["Resolved"], "by_status": dict(status_counts), "by_category": dict(category_counts), "by_department": dict(dept_counts), "recent": [ticket_payload(t, include_private=True) for t in recent], "demo_records": Complaint.query.filter_by(is_demo=True).count()}})

    @app.get("/api/agents/status")
    def agent_status():
        latest = {row.agent: row.created_at for row in db.session.query(AgentEvent.agent, func.max(AgentEvent.created_at).label("created_at")).group_by(AgentEvent.agent).all()}
        uagents_enabled = os.getenv("UAGENTS_ENABLED", "false").lower() == "true"
        uagents_available = find_spec("uagents") is not None
        route_runtime = "Local" if not uagents_enabled else ("uAgents configured" if uagents_available else "uAgents dependency unavailable")
        route_status = "Ready" if not uagents_enabled else ("Runtime not verified" if uagents_available else "Install optional runtime")
        agents = [{"name": "User Interface Agent", "responsibility": "Validates input and orchestrates the complaint workflow.", "runtime": "Local", "status": "Ready", "last_activity": iso(latest.get("User Interface Agent"))}, {"name": "Analysis Agent", "responsibility": "Creates validated structured civic issue data.", "runtime": "Local", "status": "Local fallback active" if not os.getenv("GEMINI_API_KEY") else "Gemini configured; fallback enabled", "last_activity": iso(latest.get("Analysis Agent"))}, {"name": "Routing Agent", "responsibility": "Applies database-backed department rules and creates tickets.", "runtime": route_runtime, "status": route_status, "last_activity": iso(latest.get("Routing Agent"))}]
        return jsonify({"data": {"agents": agents, "agentverse": "Not configured" if not os.getenv("AGENTVERSE_URL") else "Configured (not health-verified)", "communication": "Local function orchestration" if not uagents_enabled else "uAgents setting enabled; remote messaging requires separately started, verified agents"}})

    @app.get("/api/agents/events")
    @require_admin
    def agent_events():
        rows = AgentEvent.query.order_by(AgentEvent.created_at.desc()).limit(50).all()
        return jsonify({"data": [{"ticket_reference": e.ticket_reference, "stage": e.stage, "agent": e.agent, "outcome": e.outcome, "detail": e.detail, "mode": e.mode, "at": iso(e.created_at)} for e in rows]})

    @app.errorhandler(400)
    def bad_request(_): return api_error("The request could not be parsed.", 400, "bad_request")

    @app.errorhandler(404)
    def not_found(_): return api_error("Endpoint not found.", 404, "not_found")
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_ENV") == "development")
