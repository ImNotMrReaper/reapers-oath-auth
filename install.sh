#!/usr/bin/env bash
#
# Reaper Auth Engine: Sovereign Multi-Tier Biometric & SSH Authentication Suite
# (c) Mr. Reaper - Autonomous Pair-Programming Certified
#
# Modes:
#   sudo ./install.sh              -> Full Workstation (Face ID + Fingerprint + SSH Askpass)
#   sudo ./install.sh --server     -> Remote Server (ARM/x86 Headless Biometric Target)
#   sudo ./install.sh --client     -> Client-Only Workstation (SSH Askpass hook only)
#

set -e

GREEN="\033[1;32m"
BLUE="\033[1;34m"
PURPLE="\033[1;35m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"

echo -e "${PURPLE}================================================================${RESET}"
echo -e "${BLUE} 🛡️  REAPER AUTH ENGINE: Universal Sovereign Biometrics Installer${RESET}"
echo -e "${PURPLE}================================================================${RESET}"

# Require root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}❌ Please run this installer with sudo:${RESET}"
    echo -e "   sudo ./install.sh [options]"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)

# Mode check: Server-side installation
if [ "$1" = "--server" ] || [ "$1" = "-s" ]; then
    echo -e "\n${BLUE}>>> [SERVER MODE] Configuring Host for Remote Biometric Passthrough...${RESET}"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq
        apt-get install -y -qq libpam-ssh-agent-auth
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y pam_ssh_agent_auth || true
    elif command -v pacman >/dev/null 2>&1; then
        pacman -S --needed --noconfirm pam_ssh_agent_auth || true
    fi

    # 1. Sudoers environment preservation
    mkdir -p /etc/sudoers.d
    echo 'Defaults env_keep += "SSH_AUTH_SOCK"' > /etc/sudoers.d/ssh-agent-auth
    chmod 440 /etc/sudoers.d/ssh-agent-auth
    echo -e "    ${GREEN}✓ Preserved SSH_AUTH_SOCK in /etc/sudoers.d/ssh-agent-auth${RESET}"

    # 2. PAM sudo stack configuration
    if [ -f "/etc/pam.d/sudo" ]; then
        if ! grep -q "pam_ssh_agent_auth.so" /etc/pam.d/sudo; then
            sed -i '1a auth    sufficient    pam_ssh_agent_auth.so file=%h/.ssh/authorized_keys' /etc/pam.d/sudo
            echo -e "    ${GREEN}✓ Injected pam_ssh_agent_auth.so into /etc/pam.d/sudo${RESET}"
        else
            echo -e "    ${YELLOW}ℹ️  pam_ssh_agent_auth.so already configured in /etc/pam.d/sudo${RESET}"
        fi
    fi

    # 3. Optional local hardware fingerprint support if reader attached
    if [ -d "${SCRIPT_DIR}/src" ] && [ -f "${SCRIPT_DIR}/src/libfprint_bz3_override.c" ]; then
        echo -e "    Compiling optional local Bozorth3 override library for server..."
        mkdir -p /usr/local/lib /usr/local/bin /lib/security
        gcc -O2 -fPIC -shared -o /usr/local/lib/libfprint_bz3_override.so "${SCRIPT_DIR}/src/libfprint_bz3_override.c" -ldl 2>/dev/null || true
        cp "${SCRIPT_DIR}/bin/reaper-fprint-auth" /usr/local/bin/ 2>/dev/null || true
        cp "${SCRIPT_DIR}/bin/reaper-fingerprint" /usr/local/bin/ 2>/dev/null || true
        cp "${SCRIPT_DIR}/pam/reaper_fprint_pam.py" /lib/security/ 2>/dev/null || true
    fi

    echo -e "\n${GREEN}================================================================${RESET}"
    echo -e "${GREEN} 🎉 SERVER-SIDE BIOMETRIC AUTHENTICATION ARMED!${RESET}"
    echo -e "${GREEN}================================================================${RESET}"
    echo -e "Incoming SSH sessions with agent forwarding will now challenge your laptop's"
    echo -e "Face ID and Fingerprint sensors to authenticate remote sudo requests.\n"
    exit 0
fi

# Auto-clone repository if executed directly from curl/pipe
if [ ! -d "${SCRIPT_DIR}/src" ] || [ ! -f "${SCRIPT_DIR}/src/libfprint_bz3_override.c" ]; then
    echo ">>> Running from remote pipe. Cloning latest repository..."
    TMP_CLONE="$(mktemp -d /tmp/reaper-auth-install.XXXXXX)"
    if ! command -v git >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y -qq git;
        elif command -v dnf >/dev/null 2>&1; then dnf install -y git;
        elif command -v pacman >/dev/null 2>&1; then pacman -Sy --needed --noconfirm git;
        elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install git; fi
    fi
    git clone --depth 1 https://github.com/ImNotMrReaper/reaper-auth-engine.git "${TMP_CLONE}"
    SCRIPT_DIR="${TMP_CLONE}"
    trap "rm -rf '${TMP_CLONE}'" EXIT
fi

echo -e "\n${BLUE}>>> Step 1: Installing Core Dependencies...${RESET}"
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq fprintd libfprint-2-2 gcc build-essential python3-gi gir1.2-glib-2.0 zenity libnotify-bin
    apt-get install -y -qq libpam-python 2>/dev/null || true
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y fprintd libfprint gcc glib2-devel python3-gobject zenity libnotify
elif command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm fprintd libfprint gcc glib2 python-gobject zenity libnotify
fi

echo -e "\n${BLUE}>>> Step 2: Compiling Bozorth3 Sensitivity Override...${RESET}"
mkdir -p /usr/local/lib
gcc -O2 -fPIC -shared -o /usr/local/lib/libfprint_bz3_override.so "${SCRIPT_DIR}/src/libfprint_bz3_override.c" -ldl
chmod 755 /usr/local/lib/libfprint_bz3_override.so
echo -e "    ${GREEN}✓ Compiled:${RESET} /usr/local/lib/libfprint_bz3_override.so"

echo -e "\n${BLUE}>>> Step 3: Installing Binaries & Multi-Device Bridges...${RESET}"
mkdir -p /usr/local/bin /lib/security /usr/lib/openssh

cp "${SCRIPT_DIR}/bin/reaper-auth" /usr/local/bin/reaper-auth
chmod 755 /usr/local/bin/reaper-auth

cp "${SCRIPT_DIR}/bin/reaper-fprint-auth" /usr/local/bin/reaper-fprint-auth
chmod 755 /usr/local/bin/reaper-fprint-auth
ln -sf /usr/local/bin/reaper-fprint-auth /usr/local/bin/dp-auth

cp "${SCRIPT_DIR}/bin/reaper-fingerprint" /usr/local/bin/reaper-fingerprint
chmod 755 /usr/local/bin/reaper-fingerprint
ln -sf /usr/local/bin/reaper-fingerprint /usr/local/bin/dp-fingerprint

cp "${SCRIPT_DIR}/bin/reaper-ssh-askpass" /usr/local/bin/reaper-ssh-askpass
chmod 755 /usr/local/bin/reaper-ssh-askpass
ln -sf /usr/local/bin/reaper-ssh-askpass /usr/lib/openssh/ssh-askpass
ln -sf /usr/local/bin/reaper-ssh-askpass /usr/bin/ssh-askpass

cp "${SCRIPT_DIR}/pam/reaper_fprint_pam.py" /lib/security/reaper_fprint_pam.py
chmod 644 /lib/security/reaper_fprint_pam.py
ln -sf /lib/security/reaper_fprint_pam.py /lib/security/dp_fprint_pam.py

echo -e "    ${GREEN}✓ Installed CLI:${RESET} reaper-auth, reaper-fprint-auth, reaper-fingerprint"
echo -e "    ${GREEN}✓ Installed Askpass:${RESET} reaper-ssh-askpass -> /usr/lib/openssh/ssh-askpass"

echo -e "\n${BLUE}>>> Step 4: Configuring Systemd Service Overrides...${RESET}"
mkdir -p /etc/systemd/system/fprintd.service.d
cp "${SCRIPT_DIR}/systemd/fprintd-override.conf" /etc/systemd/system/fprintd.service.d/override.conf
chmod 644 /etc/systemd/system/fprintd.service.d/override.conf

systemctl daemon-reload
systemctl restart fprintd || true
echo -e "    ${GREEN}✓ fprintd armed with Bozorth3 tuner (14/40)${RESET}"

# User systemd ssh-agent override
if [ -n "$TARGET_HOME" ] && [ -d "$TARGET_HOME" ]; then
    SSH_AGENT_DIR="${TARGET_HOME}/.config/systemd/user/ssh-agent.service.d"
    mkdir -p "$SSH_AGENT_DIR"
    cp "${SCRIPT_DIR}/systemd/ssh-agent-override.conf" "${SSH_AGENT_DIR}/override.conf"
    chown -R "$TARGET_USER:$TARGET_USER" "${TARGET_HOME}/.config/systemd" 2>/dev/null || true
    echo -e "    ${GREEN}✓ Configured user ssh-agent service override${RESET}"

    # Shell profile hook
    if [ -f "${TARGET_HOME}/.bashrc" ]; then
        # Clean any old askpass entries
        sed -i '/ssh-biometric-askpass/d' "${TARGET_HOME}/.bashrc"
        if ! grep -q "reaper-ssh-askpass" "${TARGET_HOME}/.bashrc"; then
            cat << 'EOF' >> "${TARGET_HOME}/.bashrc"

# Reaper Auth Engine: Sovereign Biometric SSH Agent Integration
export SSH_AUTH_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/openssh_agent"
export SSH_ASKPASS="/usr/local/bin/reaper-ssh-askpass"
export SSH_ASKPASS_REQUIRE="prefer"
if [ -n "$SSH_AUTH_SOCK" ] && [ -S "$SSH_AUTH_SOCK" ]; then
    if ! ssh-add -l 2>/dev/null | grep -q "id_ed25519"; then
        ssh-add -c "$HOME/.ssh/id_ed25519" 2>/dev/null
    fi
fi
EOF
            echo -e "    ${GREEN}✓ Configured shell hook in ~/.bashrc${RESET}"
        fi
    fi
fi

echo -e "\n${BLUE}>>> Step 5: Configuring Master PAM Stack...${RESET}"
configure_pam_service() {
    local pam_file="$1"
    if [ -f "$pam_file" ]; then
        if ! grep -q "reaper_fprint_pam.py\|dp_fprint_pam.py" "$pam_file"; then
            sed -i '/pam_unix\.so/i auth\tsufficient\tpam_python.so /lib/security/reaper_fprint_pam.py' "$pam_file"
            echo -e "    ${GREEN}✓ Updated:${RESET} ${pam_file}"
        fi
    fi
}

configure_pam_service "/etc/pam.d/sudo"
configure_pam_service "/etc/pam.d/polkit-1"
configure_pam_service "/etc/pam.d/common-auth"

echo -e "\n${GREEN}================================================================${RESET}"
echo -e "${GREEN} 🎉 REAPER AUTH ENGINE INSTALLED & ARMED SUCCESSFULLY!${RESET}"
echo -e "${GREEN}================================================================${RESET}"
echo -e "  • Face ID (Howdy) + Multi-Device Fingerprint + SSH Passthrough active"
echo -e "  • Run \033[1;35mreaper-auth status\033[0m to inspect subsystem status"
echo -e "  • Run \033[1;35mreaper-auth test\033[0m to test live verification\n"
