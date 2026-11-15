# PHASE 7 — DATABASE BACKUP AND RECOVERY GUIDE

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 7 (Database Backup and Recovery)
**Status:** Procedures documented (backup/restore not yet tested on production PostgreSQL)

---

## 1. Overview

The platform supports two database configurations:

| Configuration | Use case | Database |
|---------------|----------|----------|
| Development | Local demonstration, single-user | SQLite (`backend/dev.db`) |
| Production | Multi-user, controlled pilot, public | PostgreSQL (`docker-compose.yml` `db` service) |

**Do not delete or recreate the database. Do not truncate historical records. Do not overwrite an existing backup.**

Before any risky operation, create a recoverable backup of the database and relevant configuration.

---

## 2. Development Database (SQLite)

Location: `backend/dev.db`

The database file is gitignored (`*.db`, `*.sqlite`) and must not be committed.

### 2.1 Backup command

```powershell
# From repository root
Copy-Item "backend\dev.db" "backend\dev.db.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Or, for a consistent backup while the backend is running, use SQLite's `.backup` command:

```powershell
python -c "
import sqlite3
src = sqlite3.connect('backend/dev.db')
dst = sqlite3.connect('backend/dev.db.bak')
src.backup(dst)
dst.close()
src.close()
print('SQLite backup complete: backend/dev.db.bak')
"
```

### 2.2 Backup location

`backend/dev.db.bak-<timestamp>` (same directory as the database).

Store backups outside the repository when possible (e.g., `backups/` directory). Do not commit backup files to Git.

### 2.3 Backup validation

```powershell
python -c "
import sqlite3
conn = sqlite3.connect('backend/dev.db.bak')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM bids')
print('Bids in backup:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM products')
print('Products in backup:', cur.fetchone()[0])
conn.close()
"
```

A valid backup returns non-zero counts matching the source database.

### 2.4 Restore command

```powershell
# Stop backend first
.\stop_services.ps1

# Restore from backup
Copy-Item "backend\dev.db.bak-<timestamp>" "backend\dev.db" -Force

# Restart backend
.\start_services.ps1
```

### 2.5 Restore verification

After restore:
1. `Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/v1/health"` → HTTP 200, `database_connected: true`
2. Login works with existing credentials.
3. Bid counts match the backup (verified via `SELECT COUNT(*) FROM bids`).

### 2.6 Migration (SQLite → PostgreSQL)

**Do not automatically migrate or copy the live development database into production without a verified migration plan and owner approval.**

If migration is approved:
1. Provision PostgreSQL (via `docker-compose.yml` or existing instance).
2. Set `DATABASE_URL=postgresql://...` in `backend/.env`.
3. Run `python -m alembic upgrade head` from `backend/`.
4. Run `python app/seed.py` from `backend/` to seed products.
5. Verify application starts and health endpoint responds.

---

## 3. Production Database (PostgreSQL)

Configuration exists in `docker-compose.yml`:

```yaml
db:
  image: postgres:15-alpine
  environment:
    POSTGRES_USER: securedapp
    POSTGRES_PASSWORD: <owner-supplied>
    POSTGRES_DB: securedapp_gem
  volumes:
    - postgres_data:/var/lib/postgresql/data
```

### 3.1 Backup command (pg_dump)

```bash
# From repository root
docker exec securedapp_db pg_dump -U securedapp -d securedapp_gem > backups/securedapp_gem-$(date +%Y%m%d-%H%M%S).sql
```

Or with compressed output:
```bash
docker exec securedapp_db pg_dump -U securedapp -d securedapp_gem | gzip > backups/securedapp_gem-$(date +%Y%m%d-%H%M%S).sql.gz
```

**Never include database passwords in this guide or in scripts.** Supply `PGPASSWORD` via environment or secret manager.

### 3.2 Backup location

`backups/` directory (create outside the repository). Store off-server when possible.

### 3.3 Backup validation

```bash
# Validate the dump is restorable (dry-run on a test database)
docker exec -i securedapp_db pg_restore --clean --if-exists -U securedapp -d securedapp_gem < backups/securedapp_gem-<timestamp>.sql
```

Or verify row counts:
```bash
docker exec securedapp_db psql -U securedapp -d securedapp_gem -c "SELECT COUNT(*) FROM bids;"
```

### 3.4 Restore command (pg_restore / psql)

```bash
# Stop backend first to prevent writes during restore
# (docker-compose stop backend)

# Restore from SQL dump
cat backups/securedapp_gem-<timestamp>.sql | docker exec -i securedapp_db psql -U securedapp -d securedapp_gem

# Or from gzip
zcat backups/securedapp_gem-<timestamp>.sql.gz | docker exec -i securedapp_db psql -U securedapp -d securedapp_gem
```

### 3.5 Restore verification

1. Backend health: `GET /api/v1/health` → `{"status":"ok", "database_connected": true}`
2. Row counts match backup: `SELECT COUNT(*) FROM bids;`
3. Login works with existing credentials.
4. Recent bids and notifications visible.

### 3.6 Migration procedure (Alembic)

```bash
# From backend/
python -m alembic upgrade head
```

Seed products (if needed):
```bash
python app/seed.py
```

### 3.7 Migration rollback strategy

```bash
# Rollback one migration
python -m alembic downgrade -1

# Rollback to specific revision
python -m alembic downgrade <revision_id>
```

Always backup before migrating. Test migration rollback on a staging copy before production.

---

## 4. Recovery Procedure

### Scenario: Database corruption or data loss

1. **Stop the backend** to prevent further writes.
2. **Identify the most recent valid backup.**
3. **Restore** from backup (SQLite: copy file; PostgreSQL: pg_restore/psql).
4. **Validate** row counts and application health.
5. **Restart the backend.**
6. **Verify** login and bid data integrity.

### Scenario: Failed migration

1. **Stop the backend.**
2. **Restore database** from pre-migration backup.
3. **Rollback migration** (`alembic downgrade`).
4. **Restart the backend.**
5. **Verify** health and functionality.

### Scenario: Backend crash (database intact)

1. **Restart the backend** (`.\start_services.ps1` or docker-compose).
2. **Verify** health endpoint: HTTP 200.
3. **Verify** GeM scheduler resumes: check `logs/backend-uvicorn.log` for "GeM direct scheduler started".

---

## 5. Database Health Monitoring

- **Health endpoint:** `GET /api/v1/health` → includes `database_connected`
- **GeM collector status:** `GET /api/v1/ingestion/gem-direct/status`
- **Collection runs table:** tracks each collection attempt (status, inserted, updated, duplicates)
- **Logs:** `logs/backend-uvicorn.log`

---

## 6. Checklist

| Item | Status |
|------|--------|
| SQLite backup command documented | ✅ |
| SQLite backup validation documented | ✅ |
| SQLite restore command documented | ✅ |
| SQLite restore verification documented | ✅ |
| PostgreSQL backup command (pg_dump) documented | ✅ |
| PostgreSQL restore command documented | ✅ |
| Alembic migration procedure documented | ✅ |
| Alembic rollback strategy documented | ✅ |
| Recovery procedure documented | ✅ |
| Backup tested on production PostgreSQL | ❌ (not yet — production not live) |
| Restore tested on production PostgreSQL | ❌ (not yet — production not live) |
| Database passwords excluded from guide | ✅ |

---

## 7. What Not to Do

- Do not delete or recreate the database.
- Do not truncate historical records.
- Do not overwrite an existing backup.
- Do not commit `.db`, `.sqlite`, or backup files to Git.
- Do not include database passwords in scripts or reports.
- Do not migrate dev.db to production without owner approval and a verified plan.
- Do not run restore while the backend is writing to the database.

---

*End of Database Backup and Recovery Guide*
