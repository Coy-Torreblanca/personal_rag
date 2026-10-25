#!/bin/bash
# Dump the Postgres database, upload it to R2 under a timestamped key,
# and prune backups older than BACKUP_RETENTION_DAYS.
set -euo pipefail

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
BACKUP_PREFIX="${BACKUP_PREFIX:-backups/postgres}"
BACKUP_NAME="${BACKUP_NAME:-30ai-postgres}"

# ==========================================
# AWS CLI configuration for R2
# ==========================================
export AWS_ACCESS_KEY_ID="$ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SECRET_KEY"
# R2 requires a region to be set for the AWS CLI, though it ignores the value.
export AWS_DEFAULT_REGION="auto"
# Only send checksums when the operation requires them; R2 rejects some
# of the newer default checksum headers.
export AWS_REQUEST_CHECKSUM_CALCULATION="when_required"
export AWS_RESPONSE_CHECKSUM_VALIDATION="when_required"
R2_ENDPOINT="https://${ACCOUNT_ID}.r2.cloudflarestorage.com"
BACKUP_URI="s3://${BUCKET_NAME}/${BACKUP_PREFIX}"

log() { echo "[backup $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ==========================================
# Take backup
# ==========================================
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="${BACKUP_NAME}-${TIMESTAMP}.dump"
DUMP_PATH="/tmp/${BACKUP_FILE}"
trap 'rm -f "$DUMP_PATH"' EXIT

log "Taking postgres backup of ${POSTGRES_DB} on ${POSTGRES_HOST}..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$POSTGRES_HOST" -p 5432 -F c \
  -d "$POSTGRES_DB" -U "$POSTGRES_USER" -f "$DUMP_PATH"

# Make sure the archive is readable before it replaces anything.
pg_restore --list "$DUMP_PATH" > /dev/null
log "Local backup completed ($(du -h "$DUMP_PATH" | cut -f1))."

# ==========================================
# Upload
# ==========================================
log "Uploading ${BACKUP_FILE} to ${BACKUP_URI}/..."
aws s3 cp "$DUMP_PATH" "${BACKUP_URI}/${BACKUP_FILE}" \
  --endpoint-url "$R2_ENDPOINT" --only-show-errors
log "Upload successful."

log "Backup finished."
