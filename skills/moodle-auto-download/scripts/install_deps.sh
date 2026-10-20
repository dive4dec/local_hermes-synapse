#!/bin/sh
# Exit immediately upon encountering an error
set -e

# 1. Dynamic privilege escalation logic: use `sudo` only if the user is not `root` and `sudo` is present on the system.
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "Error: Executing this script requires root privileges or the sudo command." >&2
        exit 1
    fi
else
    SUDO=""
fi

# 2. Automatically detect the package manager and install dependencies
if command -v apk >/dev/null 2>&1; then
    echo "Alpine Linux (apk) environment detected..."
    $SUDO apk update
    echo "Installing Python, network tools, Chromium, and PHP-FPM..."
    $SUDO apk add --no-cache python3 py3-requests py3-websocket-client socat chromium php-fpm

    echo "Configuring www-data user..."
    # Alpine does not have a `www-data` user by default; it must be created manually.
    if ! id -u www-data > /dev/null 2>&1; then
        $SUDO addgroup -g 82 -S www-data
        $SUDO adduser -u 82 -D -S -G www-data www-data[cite: 2]
        echo "Successfully created www-data user and group."
    fi

elif command -v apt-get >/dev/null 2>&1; then
    echo "Ubuntu/Debian (apt-get) environment detected..."
    $SUDO apt-get update
    echo "Installing dependencies..."
    $SUDO apt-get install -y python3 python3-requests python3-websocket socat chromium-browser php-fpm
else
    echo "Error: No supported package manager found (only apk or apt-get are supported)." >&2
    exit 1
fi

# 3. Standardize PHP-FPM Execution Permissions
echo "Configuring PHP-FPM..."
FPM_CONF=$(find /etc/php* /etc/php -name "www.conf" 2>/dev/null | head -n 1)
if [ -n "$FPM_CONF" ]; then
    echo "Updating configuration file: $FPM_CONF..."
    $SUDO sed -i 's/^user = .*/user = www-data/' "$FPM_CONF"
    $SUDO sed -i 's/^group = .*/group = www-data/' "$FPM_CONF"
else
    echo "Warning: PHP-FPM www.conf not found; please verify the configuration manually."
fi

echo "All dependencies installed and configured!"