FROM docker.io/library/alpine:3.22

RUN apk add --no-cache postgresql16-client aws-cli bash

COPY packages/database/backup/take_backup.sh /usr/local/bin/take_backup.sh
COPY packages/database/backup/restore_backup.sh /usr/local/bin/restore_backup.sh

RUN chmod +x /usr/local/bin/take_backup.sh /usr/local/bin/restore_backup.sh

# crond starts jobs with an empty environment, so the container env is
# snapshotted at startup and sourced by the job. Output goes to PID 1's
# stdout so it shows up in `podman logs`.
RUN echo "0 * * * * . /root/project_env.sh && /usr/local/bin/take_backup.sh > /proc/1/fd/1 2>&1" > /etc/crontabs/root

CMD export -p > /root/project_env.sh && chmod 600 /root/project_env.sh && crond -f -l 2
