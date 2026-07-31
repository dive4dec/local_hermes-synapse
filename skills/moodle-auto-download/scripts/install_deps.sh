#!/bin/sh
# Exit immediately if a command exits with a non-zero status
set -e

echo "Updating apk repositories..."
apk update

echo "Installing Python and networking dependencies..."
# The Python script requires Python 3, requests, and websocket-client. 
# socat is installed for CDP port tunneling.
apk add python3 py3-requests py3-websocket-client socat

echo "Installing Chromium..."
# The script requires a Chromium/Chrome binary to launch headless browser sessions.
apk add chromium

echo "Configuring www-data user..."
# Alpine does not have www-data by default; we must create it.
if ! id -u www-data > /dev/null 2>&1; then
    addgroup -g 82 -S www-data
    adduser -u 82 -D -S -G www-data www-data
    echo "Created www-data user and group."
fi

echo "Installing and configuring PHP-FPM..."
# Install standard PHP-FPM
apk add php-fpm

# Update the PHP-FPM www.conf file to drop privileges to www-data.
# PHP-FPM's main service runs as root, but worker processes will run as www-data.
FPM_CONF=$(find /etc/php* -name "www.conf" | head -n 1)
if [ -n "$FPM_CONF" ]; then
    echo "Updating PHP-FPM configuration in $FPM_CONF..."
    sed -i 's/^user = .*/user = www-data/' "$FPM_CONF"
    sed -i 's/^group = .*/group = www-data/' "$FPM_CONF"
else
    echo "Warning: PHP-FPM www.conf not found. Manual configuration required."
fi

echo "All dependencies installed and configured successfully!"