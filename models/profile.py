from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.mutable import MutableList

from models import db


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    home_address = db.Column(db.String(255))
    home_lat = db.Column(db.Float)
    home_lng = db.Column(db.Float)
    school_name = db.Column(db.String(255))
    school_address = db.Column(db.String(255))
    school_lat = db.Column(db.Float)
    school_lng = db.Column(db.Float)
    days_per_week = db.Column(db.Integer, default=4)
    trips_per_day = db.Column(db.Integer, default=2)
    commute_time_preference = db.Column(db.String(20), default="AM")
    transport_modes = db.Column(MutableList.as_mutable(db.JSON), default=list)
    weekly_budget = db.Column(db.Float, default=34.0)
    budget_alert_50 = db.Column(db.Boolean, default=True)
    budget_alert_80 = db.Column(db.Boolean, default=True)
    car_mpg = db.Column(db.Float, default=28.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="profile")
