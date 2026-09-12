#!/bin/bash

# ==========================================
# Take backup.
# ==========================================

echo "Taking postgres bakcup..."
PGPASSWORD=$POSTGRES_PASSWORD pg_dump -h 30ai-postgres -p 5432 -F c -d $POSTGRES_DB -U $POSTGRES_USER -f $BACKUP_FILE_NAME
echo "Local postgres backup completed..."


# ==========================================
# Export AWS CLI Environment Variables
# ==========================================
export AWS_ACCESS_KEY_ID="$ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SECRET_KEY"
# R2 requires a region to be set for the AWS CLI, though it ignores the value. 
# "auto" or "us-east-1" are standard for R2.
export AWS_DEFAULT_REGION="auto" 

# ==========================================
# Upload Command
# ==========================================
echo "Uploading $BACKUP_FILE_NAME.dump to R2 bucket: $BUCKET_NAME..."

aws s3 cp "$BACKUP_FILE_NAME" "s3://$BUCKET_NAME/$BACKUP_FILE_NAME" \
  --endpoint-url "https://${ACCOUNT_ID}.r2.cloudflarestorage.com"

if [ $? -eq 0 ]; then
    echo "Upload successful!"
else
    echo "Upload failed."
fi

rm $BACKUP_FILE_NAME

echo "Deleted $BACKUP_FILE_NAME"
