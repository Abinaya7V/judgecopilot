# ShiftSwap

A peer-to-peer shift-trading platform for hourly retail/restaurant
workers, with automatic manager approval routing and conflict detection.

## Problem

Hourly workers routinely need to swap shifts (childcare, second jobs,
school), but most workplaces still coordinate this via group texts —
managers find out after the fact, double-bookings happen, and labor-law
constraints (max hours, required rest between shifts) go unchecked.

## What makes this different

Existing shift-swap tools (When I Work, Deputy) require the employer to
already be on that platform. ShiftSwap is designed to sit *alongside*
any existing scheduling system — workers upload their schedule (CSV
export from whatever tool their employer uses), and swaps are proposed,
validated against labor constraints, and routed for manager approval
without requiring the employer to migrate anything.

## Architecture

- FastAPI backend, PostgreSQL via SQLAlchemy
- Constraint engine checks: max weekly hours, minimum rest between
  shifts (state-configurable, defaults to 8hr), and double-booking
  before a swap is even proposed to the manager
- Redis-backed notification queue (swap proposed → other worker → 
  manager approval → both parties notified)
- Full test suite: unit tests for the constraint engine, integration
  tests for the swap-approval state machine

## Setup

```bash
docker-compose up -d          # starts postgres + redis
pip install -r requirements.txt
alembic upgrade head          # run migrations
uvicorn main:app --reload
```

Run tests: `pytest --cov=app tests/` (currently at 78% coverage)

## Demo

Live demo (seeded with sample schedule data): https://shiftswap-demo.example.com
Walkthrough video (4 min, shows full swap flow including a rejected
swap that violates rest-hour constraints): https://demo-video.example.com/shiftswap

## Known limitations

- CSV import currently supports 3 common scheduling export formats;
  falls back to manual entry for others
- Labor-law constraint rules are US-defaults; not yet configurable per
  state/country regulation
- No mobile app yet — mobile-responsive web only
