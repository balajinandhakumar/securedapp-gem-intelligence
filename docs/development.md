# Development Guide & Setup Instructions

## Prerequisites
- Python 3.10+ (or Python 3.11 / 3.14)
- Docker & Docker Compose
- Virtualenv

## Local Setup (Without Docker)
1. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Run migrations and seed products:
   ```bash
   cd backend
   python app/seed.py
   ```
4. Start FastAPI dev server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
5. Run tests:
   ```bash
   pytest tests/
   ```

## Running via Docker Compose
1. Build and start containers:
   ```bash
   docker-compose up --build -d
   ```
2. Access API documentation at `http://localhost:8000/docs`
