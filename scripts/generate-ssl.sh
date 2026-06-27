#!/bin/bash
# Generate self-signed SSL certificates for development/testing

set -e

echo "Generating self-signed SSL certificates for OAuth2 Log Streamer..."
echo "These certificates are for DEVELOPMENT/TESTING only!"
echo ""

# Create ssl directory if it doesn't exist
mkdir -p ssl

# Generate private key
openssl genrsa -out ssl/privkey.pem 2048

# Generate certificate signing request
openssl req -new -key ssl/privkey.pem -out ssl/csr.pem -subj "/CN=localhost"

# Generate self-signed certificate
openssl x509 -req -days 365 -in ssl/csr.pem -signkey ssl/privkey.pem -out ssl/fullchain.pem

# Clean up CSR
rm ssl/csr.pem

# Set proper permissions
chmod 600 ssl/privkey.pem
chmod 644 ssl/fullchain.pem

echo ""
echo "SSL certificates generated:"
echo "  - ssl/privkey.pem (private key)"
echo "  - ssl/fullchain.pem (certificate)"
echo ""
echo "To use these certificates, add the following to your /etc/hosts:"
echo "  127.0.0.1 localhost"
echo ""
echo "Then access: https://localhost (your browser will warn about self-signed cert)"
