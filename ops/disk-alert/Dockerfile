# syntax=docker/dockerfile:1.7
FROM alpine:3.20

RUN apk add --no-cache curl tini

COPY entrypoint.sh /entrypoint.sh
COPY check-disk.sh /usr/local/bin/check-disk.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/check-disk.sh

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
