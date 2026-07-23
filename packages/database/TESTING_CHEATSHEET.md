# Open shell to database

```bash
podman exec -it 30ai-postgres psql -U 30ai_user -d 30ai_db
```
Note - username, password, and db are defined in docker compose.

```
30ai_db=# \dt
              List of relations
 Schema |      Name       | Type  |   Owner   
--------+-----------------+-------+-----------
 public | alembic_version | table | 30ai_user
 public | document_chunks | table | 30ai_user
 public | documents       | table | 30ai_user
 public | organizations   | table | 30ai_user
 public | processing_jobs | table | 30ai_user
 public | users           | table | 30ai_user
(6 rows)

30ai_db=# select * from documents;
```

