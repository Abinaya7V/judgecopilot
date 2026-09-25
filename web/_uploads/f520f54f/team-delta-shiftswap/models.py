"""SQLAlchemy models for ShiftSwap."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class SwapStatus(enum.Enum):
    PROPOSED = "proposed"
    ACCEPTED_BY_PEER = "accepted_by_peer"
    PENDING_MANAGER = "pending_manager"
    APPROVED = "approved"
    REJECTED = "rejected"
    REJECTED_CONSTRAINT_VIOLATION = "rejected_constraint_violation"


class Worker(Base):
    __tablename__ = "workers"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    employer_id = Column(Integer, ForeignKey("employers.id"), nullable=False)
    weekly_hour_cap = Column(Integer, default=40)

    shifts = relationship("Shift", back_populates="worker")


class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)

    worker = relationship("Worker", back_populates="shifts")


class SwapRequest(Base):
    __tablename__ = "swap_requests"
    id = Column(Integer, primary_key=True)
    requesting_shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    target_worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    status = Column(Enum(SwapStatus), default=SwapStatus.PROPOSED)
    manager_approved = Column(Boolean, default=False)
    constraint_violation_reason = Column(String, nullable=True)
