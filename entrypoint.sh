#!/bin/sh
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Create group and user if they don't already exist
if ! getent group questsmith > /dev/null 2>&1; then
    addgroup --gid "$PGID" questsmith
fi

if ! getent passwd questsmith > /dev/null 2>&1; then
    adduser --disabled-password --gecos "" --no-create-home --uid "$PUID" --ingroup questsmith questsmith
else
    usermod -o -u "$PUID" questsmith 2>/dev/null
    groupmod -o -g "$PGID" questsmith 2>/dev/null
fi

# Ensure data directory exists and has correct ownership
mkdir -p /app/data /app/uploads
chown -R "$PUID:$PGID" /app/data /app/uploads

exec gosu questsmith "$@"
