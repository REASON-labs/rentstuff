# rentstuff — Rental listing board

## What this is
Flask web app for managing rental listings. Public-facing browse + admin panel.

## Stack
- **Flask 3.x** (Python 3.12)
- **Flask-WTF** for forms
- **Gunicorn** for production serving
- **SQLite** for data storage
- **Pillow** for image processing
- **Docker** deployment (:8000)

## Structure
- `app/` — Flask application
- `app/routes/` — route handlers (Flask blueprints)
- `app/static/` — CSS, images
- `app/templates/` — Jinja2 templates
- `app/templates/admin/` — admin panel templates
- `app/templates/diagrams/` — diagram templates
- `tests/` — test suite

## Key files
- `app/__init__.py` — app factory
- `app/routes/` — route blueprints
- `Dockerfile` — Python 3.12 slim, gunicorn
- `docker-compose.yml` — rentstuff service on :8000
- `requirements.txt` — Flask, Flask-WTF, gunicorn, python-dotenv, Pillow

## Notes
- Admin routes under `/admin/`
- Diagram templates for visual representations
- Docker deployment on port 8000
