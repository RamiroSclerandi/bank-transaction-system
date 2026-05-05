FROM postgres:16

# Install tzdata so PostgreSQL can resolve ANY IANA timezone name
# (e.g. America/Buenos_Aires sent by DBeaver / Java clients).
# The base postgres:16 image is Debian Slim and ships without /usr/share/zoneinfo.
# Without this, every named-timezone SET request from a client causes:
#   FATAL: invalid value for parameter "TimeZone": "<name>"
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
