"""Optional Fetch.ai uAgents transport for CivicSync.

Run the analysis and routing roles as separate processes after configuring their
seeds and addresses. The routing role can submit the validated result to Flask;
Flask remains the authority for validation, routing, idempotency, and persistence.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from urllib.request import Request, urlopen

from uagents import Agent, Context, Model


CATEGORIES = ["Road Damage", "Streetlight", "Garbage", "Water Leakage", "Blocked Drain", "Public Property", "General Review"]
URGENCIES = ["Low", "Medium", "High", "Critical"]
CATEGORY_TERMS = [
    ("Blocked Drain", ("drain", "sewer", "clog", "blocked drain", "flood")),
    ("Water Leakage", ("leak", "water pipe", "water tap", "burst pipe")),
    ("Streetlight", ("streetlight", "street light", "lamp post", "lamp")),
    ("Garbage", ("garbage", "trash", "waste", "overflowing bin", "rubbish")),
    ("Road Damage", ("pothole", "road damage", "broken road", "crater", "damaged road")),
    ("Public Property", ("bench", "park", "public property", "bus stop", "signboard")),
]
DEPARTMENTS = {
    "Road Damage": "Road Maintenance", "Streetlight": "Electrical Maintenance",
    "Garbage": "Sanitation", "Water Leakage": "Water Supply",
    "Blocked Drain": "Drainage Department", "Public Property": "Public Works",
    "General Review": "General Review Queue",
}


class ComplaintRequest(Model):
    correlation_id: str
    description: str
    location: str
    category: str | None = None
    urgency: str | None = None
    title: str | None = None


class AnalysisResult(Model):
    correlation_id: str
    requester_address: str
    description: str
    title: str
    category: str
    summary: str
    location: str
    urgency: str
    missing_fields: list[str]
    confidence: float


class RoutingResult(Model):
    correlation_id: str
    department: str
    outcome: str
    ticket_reference: str | None = None
    detail: str | None = None


analysis_agent = Agent(name="civicsync_analysis", seed=os.environ["CIVICSYNC_ANALYSIS_AGENT_SEED"])
routing_agent = Agent(name="civicsync_routing", seed=os.environ["CIVICSYNC_ROUTING_AGENT_SEED"])


def analyze_message(message: ComplaintRequest) -> AnalysisResult:
    if not message.correlation_id.strip() or len(message.correlation_id.strip()) > 100:
        raise ValueError("correlation_id must contain 1 to 100 characters.")
    description = re.sub(r"\s+", " ", message.description.strip())[:2000]
    location = message.location.strip()[:220]
    lowered = description.lower()
    category = message.category if message.category in CATEGORIES[:-1] else "General Review"
    if category == "General Review":
        for candidate, terms in CATEGORY_TERMS:
            if any(term in lowered for term in terms):
                category = candidate
                break
    urgency = message.urgency if message.urgency in URGENCIES else "Medium"
    if message.urgency not in URGENCIES:
        if any(term in lowered for term in ("fire", "accident", "electrical shock", "immediate danger")):
            urgency = "Critical"
        elif any(term in lowered for term in ("school", "hospital", "heavy", "three days")):
            urgency = "High"
    missing = []
    if not location:
        missing.append("location")
    if len(description) < 12:
        missing.append("description detail")
    title = (message.title or description[:140]).strip()[:140]
    return AnalysisResult(
        correlation_id=message.correlation_id.strip()[:100], requester_address="", description=description, title=title,
        category=category, summary=title, location=location, urgency=urgency,
        missing_fields=missing, confidence=0.88 if category != "General Review" else 0.42,
    )


@analysis_agent.on_message(model=ComplaintRequest, replies={RoutingResult})
async def analyze(ctx: Context, sender: str, message: ComplaintRequest):
    try:
        result = analyze_message(message)
    except ValueError as exc:
        await ctx.send(sender, RoutingResult(
            correlation_id=(message.correlation_id or "invalid")[:100],
            department=DEPARTMENTS["General Review"],
            outcome="needs_clarification",
            detail=str(exc),
        ))
        return

    result.requester_address = sender
    routing_address = os.getenv("CIVICSYNC_ROUTING_AGENT_ADDRESS", "").strip()
    if not routing_address:
        outcome = "needs_clarification" if result.missing_fields else "routed_not_persisted"
        detail = ("Missing: " + ", ".join(result.missing_fields)) if result.missing_fields else "Set CIVICSYNC_ROUTING_AGENT_ADDRESS and start the routing agent to complete the workflow."
        await ctx.send(sender, RoutingResult(
            correlation_id=result.correlation_id,
            department=DEPARTMENTS.get(result.category, DEPARTMENTS["General Review"]),
            outcome=outcome,
            detail=detail,
        ))
        return

    try:
        await ctx.send(routing_address, result)
        ctx.logger.info("Analysis %s forwarded to routing agent", result.correlation_id)
    except Exception as exc:
        ctx.logger.error("Could not forward analysis to routing agent: %s", type(exc).__name__)
        await ctx.send(sender, RoutingResult(
            correlation_id=result.correlation_id,
            department=DEPARTMENTS.get(result.category, DEPARTMENTS["General Review"]),
            outcome="persistence_failed",
            detail="Could not contact the routing agent. Retry with the same correlation ID.",
        ))


@routing_agent.on_message(model=AnalysisResult, replies={RoutingResult})
async def route(ctx: Context, sender: str, message: AnalysisResult):
    department = DEPARTMENTS.get(message.category, DEPARTMENTS["General Review"])
    if message.missing_fields:
        await ctx.send(message.requester_address or sender, RoutingResult(
            correlation_id=message.correlation_id, department=department,
            outcome="needs_clarification", detail="Missing: " + ", ".join(message.missing_fields),
        ))
        return

    api_base = os.getenv("CIVICSYNC_FLASK_API_URL", "").strip().rstrip("/")
    if not api_base:
        await ctx.send(message.requester_address or sender, RoutingResult(
            correlation_id=message.correlation_id, department=department,
            outcome="routed_not_persisted", detail="Set CIVICSYNC_FLASK_API_URL to enable Flask persistence.",
        ))
        return

    payload = {
        "title": message.title,
        "description": message.description,
        "location": message.location,
        "category": message.category,
        "urgency": message.urgency,
    }
    request = Request(
        f"{api_base}/api/complaints", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Idempotency-Key": "uagent-" + re.sub(r"[^A-Za-z0-9_-]", "", message.correlation_id)[:90]},
        method="POST",
    )
    try:
        response_body = await asyncio.to_thread(_post_ticket, request)
        data = response_body.get("data", {})
        await ctx.send(message.requester_address or sender, RoutingResult(
            correlation_id=message.correlation_id, department=department,
            outcome="ticket_created", ticket_reference=data.get("ticket_id"),
            detail="Flask validated and persisted the ticket.",
        ))
    except Exception as exc:
        ctx.logger.error("Flask ticket persistence failed: %s", type(exc).__name__)
        await ctx.send(message.requester_address or sender, RoutingResult(
            correlation_id=message.correlation_id, department=department,
            outcome="persistence_failed", detail="Flask did not confirm ticket creation; retry with the same correlation ID.",
        ))


if __name__ == "__main__":
    role = os.getenv("CIVICSYNC_AGENT_ROLE", "analysis").lower()
    if role == "routing":
        routing_agent.run()
    else:
        analysis_agent.run()
