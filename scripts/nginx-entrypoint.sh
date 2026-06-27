#!/bin/sh

# Nginx configuration processor
# This script runs before nginx starts and substitutes environment variables
# in the nginx.conf file

set -e

# Template file path (mounted from host)
CONFIG_FILE="/etc/nginx/nginx.conf"

# Check if envsubst is available, if not install it
if ! command -v envsubst > /dev/null 2>&1; then
    echo "Installing gettext for envsubst..."
    apk add --no-cache gettext
fi

# Substitute environment variables in the nginx configuration
# Only substitute variables that are defined (to avoid replacing with empty strings)
echo "Processing nginx configuration with environment variables..."

# If INTERNAL_ALLOWED_IP is not set or empty, remove the allow line entirely
# to avoid invalid nginx syntax
if [ -z "$INTERNAL_ALLOWED_IP" ]; then
    # Remove allow lines that would be empty
    sed '/allow \${INTERNAL_ALLOWED_IP\};/d' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp"
else
    # Substitute the variable
    envsubst '${INTERNAL_ALLOWED_IP}' < "$CONFIG_FILE" > "${CONFIG_FILE}.tmp"
fi
mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"

# Validate the generated configuration
echo "Testing nginx configuration..."
nginx -t

echo "Nginx configuration processed successfully."
