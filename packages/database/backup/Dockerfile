FROM alpine:latest

RUN apk add --no-cache postgresql16-client aws-cli bash

COPY backup_db.sh /usr/local/bin/backup_db.sh

RUN chmod +x /usr/local/bin/backup_db.sh

RUN echo "0 * * * * /usr/local/bin/backup_db.sh" > /etc/crontabs/root

CMD env > /root/project_env.sh && crond -f -l 2
