#!/usr/bin/env bash
#
# Reaper Auth Engine Uninstaller
# Restores stock PAM and systemd configurations cleanly.
#

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run with sudo: sudo ./uninstall.sh"
    exit 1
fi

echo ">>> Removing Reaper Auth Engine components..."

# Remove binaries
rm -f /usr/local/bin/reaper-auth
rm -f /usr/local/bin/reaper-fprint-auth /usr/local/bin/dp-auth
rm -f /usr/local/bin/reaper-fingerprint /usr/local/bin/dp-fingerprint
rm -f /usr/local/bin/reaper-ssh-askpass /usr/local/bin/ssh-biometric-askpass
rm -f /usr/lib/openssh/ssh-askpass
rm -f /usr/bin/ssh-askpass
rm -f /lib/security/reaper_fprint_pam.py /lib/security/dp_fprint_pam.py
rm -f /usr/local/lib/libfprint_bz3_override.so

# Clean PAM
for file in /etc/pam.d/sudo /etc/pam.d/polkit-1 /etc/pam.d/common-auth; do
    if [ -f "$file" ]; then
        sed -i '/reaper_fprint_pam\.py\|dp_fprint_pam\.py/d' "$file"
    fi
done

# Clean systemd fprintd override
rm -f /etc/systemd/system/fprintd.service.d/override.conf
systemctl daemon-reload
systemctl restart fprintd || true

echo "✓ Reaper Auth Engine cleanly uninstalled."
