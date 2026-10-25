#!/bin/bash
# Delete Postgres backups in R2 older than BACKUP_PRUNE_DAYS (default 14).
set -euo pipefail

BACKUP_PREFIX="${BACKUP_PREFIX:-backups/postgres}"
BACKUP_NAME="${BACKUP_NAME:-30ai-postgres}"
BACKUP_PRUNE_DAYS="${BACKUP_PRUNE_DAYS:-14}"

# ==========================================
# AWS CLI configuration for R2
# ==========================================
export AWS_ACCESS_KEY_ID="$ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SECRET_KEY"
export AWS_DEFAULT_REGION="auto"
export AWS_REQUEST_CHECKSUM_CALCULATION="when_required"
export AWS_RESPONSE_CHECKSUM_VALIDATION="when_required"
R2_ENDPOINT="https://${ACCOUNT_ID}.r2.cloudflarestorage.com"
BACKUP_URI="s3://${BUCKET_NAME}/${BACKUP_PREFIX}"

log() { echo "[prune $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

CUTOFF=$(date -u -d "@$(( $(date +%s) - BACKUP_PRUNE_DAYS * 86400 ))" +%Y%m%dT%H%M%SZ)
log "Pruning backups older than ${BACKUP_PRUNE_DAYS} days (before ${CUTOFF})..."

DELETED=0
aws s3 ls "${BACKUP_URI}/" --endpoint-url "$R2_ENDPOINT" \
  | awk '{print $4}' \
  | { grep -E "^${BACKUP_NAME}-[0-9]{8}T[0-9]{6}Z\.dump$" || true; } \
  | while read -r key; do
      key_ts="${key#"${BACKUP_NAME}-"}"
      key_ts="${key_ts%.dump}"
      if [[ "$key_ts" < "$CUTOFF" ]]; then
        log "Deleting ${key}"
        aws s3 rm "${BACKUP_URI}/${key}" --endpoint-url "$R2_ENDPOINT" --only-show-errors
        DELETED=$((DELETED + 1))
      fi
    done

log "Prune finished. Deleted ${DELETED} backup(s)."
