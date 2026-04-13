from __future__ import annotations

from datetime import date, datetime

from models import db


class SpendLog(db.Model):
    __tablename__ = "spend_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    week_start_date = db.Column(db.Date, default=date.today, nullable=False)
    amount_spent = db.Column(db.Float, default=0.0, nullable=False)
    transport_mode = db.Column(db.String(50), nullable=False, default="subway")
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="spend_logs")
