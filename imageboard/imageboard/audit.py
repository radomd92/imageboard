"""Persistent audit records for privileged and user-generated mutations."""

from flask_login import current_user

from .database import AuditEvent, db


def record_event(action, object_type, object_id):
    event = AuditEvent(
        actor_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id)[:200],
    )
    db.session.add(event)
