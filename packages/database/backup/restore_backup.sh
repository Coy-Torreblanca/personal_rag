#!/bin/bash
# Restore the database from an R2 backup. Overwrites existing objects.
#
#   podman exec -it 30ai-postgres-backup-cron restore_backup.sh latest
#   podman exec -it 30ai-postgres-backup-cron restore_backup.sh 30ai-postgres-20261025T170000Z.dump
#
# Stop the api and workers first so nothing writes during the restore.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: restore_backup.sh <latest|backup file name>" >&2
  exit 1
fi

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
BACKUP_PREFIX="${BACKUP_PREFIX:-backups/postgres}"
BACKUP_NAME="${BACKUP_NAME:-30ai-postgres}"

export AWS_ACCESS_KEY_ID="$ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SECRET_KEY"
export AWS_DEFAULT_REGION="auto"
export AWS_REQUEST_CHECKSUM_CALCULATION="when_required"
export AWS_RESPONSE_CHECKSUM_VALIDATION="when_required"
R2_ENDPOINT="https://${ACCOUNT_ID}.r2.cloudflarestorage.com"
BACKUP_URI="s3://${BUCKET_NAME}/${BACKUP_PREFIX}"

BACKUP_FILE="$1"
if [[ "$BACKUP_FILE" == "latest" ]]; then
  BACKUP_FILE=$(aws s3 ls "${BACKUP_URI}/" --endpoint-url "$R2_ENDPOINT" \
    | awk '{print $4}' | grep -E "^${BACKUP_NAME}-.*\.dump$" | sort | tail -n 1)
  if [[ -z "$BACKUP_FILE" ]]; then
    echo "No backups found under ${BACKUP_URI}/" >&2
    exit 1
  fi
fi

DUMP_PATH="/tmp/${BACKUP_FILE}"
trap 'rm -f "$DUMP_PATH"' EXIT

echo "Downloading ${BACKUP_URI}/${BACKUP_FILE}..."
aws s3 cp "${BACKUP_URI}/${BACKUP_FILE}" "$DUMP_PATH" \
  --endpoint-url "$R2_ENDPOINT" --only-show-errors

echo "Restoring ${BACKUP_FILE} into ${POSTGRES_DB} on ${POSTGRES_HOST}..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h "$POSTGRES_HOST" -p 5432 \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner \
  --single-transaction "$DUMP_PATH"

echo "Restore complete."
