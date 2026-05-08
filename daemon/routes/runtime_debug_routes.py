"""Read-only debug and schema inspection routes. No side effects."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from flask import Flask, jsonify, request

from daemon.core.current_context_builder import CurrentContextBuilder
from daemon.core.event_debug import describe_event_for_debug
from daemon.core.event_envelope import (
    PulseEventBucket,
    PulseEventSource,
    PulsePrivacyClass,
    PulseRetention,
)
from daemon.core.timeline_builder import span_from_current_context
from daemon.core.timeline_debug import describe_timeline_span_for_debug
from daemon.core.timeline_span import TimelineSpanKind
from daemon.core.work_context_card import build_work_context_card
from daemon.memory.extractor import find_git_root
from daemon.core.workspace_context import find_workspace_root


def register_debug_routes(
    app: Flask,
    *,
    bus: Any,
    runtime_state: Any,
    current_context_builder: CurrentContextBuilder,
    parse_timestamp_fn: Callable[[Any], datetime | None],
) -> None:
    """Register read-only debug and schema inspection routes onto *app*."""

    @app.route("/events/debug")
    def get_events_debug():
        """Developer-only raw event browser preview without raw payload values."""
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = min(max(limit, 1), 200)

        since_raw = request.args.get("since")
        since_dt = parse_timestamp_fn(since_raw) if since_raw else None

        source_filter = request.args.get("source")
        bucket_filter = request.args.get("bucket")
        privacy_filter = request.args.get("privacy")
        retention_filter = request.args.get("retention")

        recent = bus.recent(limit)
        events = []
        for event in recent:
            if since_dt is not None and event.timestamp <= since_dt:
                continue
            description = describe_event_for_debug(event)
            if source_filter and description["source"] != source_filter:
                continue
            if bucket_filter and description["bucket"] != bucket_filter:
                continue
            if privacy_filter and description["privacy"] != privacy_filter:
                continue
            if retention_filter and description["retention"] != retention_filter:
                continue
            events.append(description)
        return jsonify({"events": events, "count": len(events)})

    @app.route("/events/schema")
    def get_events_schema():
        """Expose event metadata enums for debug UI / raw event browser filters."""
        return jsonify({
            "sources": [source.value for source in PulseEventSource],
            "buckets": [bucket.value for bucket in PulseEventBucket],
            "privacy_classes": [privacy.value for privacy in PulsePrivacyClass],
            "retention_classes": [retention.value for retention in PulseRetention],
        })

    @app.route("/timeline/preview")
    def get_timeline_preview():
        """Preview a passive timeline span from the current runtime context."""
        runtime_snapshot = runtime_state.get_runtime_snapshot()
        present = runtime_snapshot.present
        now = datetime.now()
        duration_min = max(int(present.session_duration_min or 0), 0)
        started_at = now - timedelta(minutes=duration_min)

        if runtime_snapshot.signals:
            context = current_context_builder.build(
                present=present,
                active_app=runtime_snapshot.latest_active_app,
                signals=runtime_snapshot.signals,
                find_git_root_fn=find_git_root,
                find_workspace_root_fn=find_workspace_root,
            )
        else:
            context = present

        span = span_from_current_context(
            context,
            started_at=started_at,
            ended_at=now,
        )
        return jsonify({
            "span": span.to_dict(),
            "debug": describe_timeline_span_for_debug(span),
        })

    @app.route("/timeline/schema")
    def get_timeline_schema():
        """Expose timeline metadata enums for debug UI / timeline filters."""
        return jsonify({
            "span_kinds": [kind.value for kind in TimelineSpanKind],
        })

    @app.route("/work-context")
    def get_work_context_card():
        """Return a passive explainable card for the current work context."""
        runtime_snapshot = runtime_state.get_runtime_snapshot()
        present = runtime_snapshot.present

        if runtime_snapshot.signals:
            current_context = current_context_builder.build(
                present=present,
                active_app=runtime_snapshot.latest_active_app,
                signals=runtime_snapshot.signals,
                find_git_root_fn=find_git_root,
                find_workspace_root_fn=find_workspace_root,
            )
        else:
            current_context = present

        card = build_work_context_card(
            current_context,
            present=present,
            signals=runtime_snapshot.signals,
            decision=runtime_snapshot.decision,
        )
        return jsonify({"card": card.to_dict()})
