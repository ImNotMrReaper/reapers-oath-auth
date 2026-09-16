#!/usr/bin/env bash
#
# Reaper's Oath Auth Engine: Universal Sovereign Biometrics Suite
# Integrates Howdy Face ID + Digital Persona / Goodix Fingerprints + Remote SSH Biometrics
# (c) Mr. Reaper - Open Source & Sovereign
#
# Modes:
#   sudo ./install.sh              -> Full Workstation (Face ID + Fingerprint + SSH Passthrough)
#   sudo ./install.sh --server     -> Remote Server (ARM / x86 Biometric Challenge Target)
#   sudo ./install.sh --client     -> Client-Only Workstation (SSH Askpass hook only)
#

set -e

GREEN="\033[1;32m"
BLUE="\033[1;34m"
PURPLE="\033[1;35m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RED="\033[1;31m"
RESET="\033[0m"

echo -e "${PURPLE}================================================================${RESET}"
echo -e "${BLUE} 🛡️  REAPER'S OATH AUTH ENGINE: Sovereign Multi-Tier Biometrics${RESET}"
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

# -------------------------------------------------------------------------
# Mode Check: Server-Side Installation
# -------------------------------------------------------------------------
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

    mkdir -p /etc/sudoers.d
    echo 'Defaults env_keep += "SSH_AUTH_SOCK"' > /etc/sudoers.d/ssh-agent-auth
    chmod 440 /etc/sudoers.d/ssh-agent-auth
    echo -e "    ${GREEN}✓ Preserved SSH_AUTH_SOCK in /etc/sudoers.d/ssh-agent-auth${RESET}"

    if [ -f "/etc/pam.d/sudo" ]; then
        if ! grep -q "pam_ssh_agent_auth.so" /etc/pam.d/sudo; then
            sed -i '1a auth    sufficient    pam_ssh_agent_auth.so file=%h/.ssh/authorized_keys' /etc/pam.d/sudo
            echo -e "    ${GREEN}✓ Injected pam_ssh_agent_auth.so into /etc/pam.d/sudo${RESET}"
        else
            echo -e "    ${YELLOW}ℹ️  pam_ssh_agent_auth.so already configured in /etc/pam.d/sudo${RESET}"
        fi
    fi

    echo -e "\n${GREEN}================================================================${RESET}"
    echo -e "${GREEN} 🎉 SERVER-SIDE BIOMETRIC AUTHENTICATION ARMED!${RESET}"
    echo -e "${GREEN}================================================================${RESET}"
    echo -e "Incoming SSH sessions with agent forwarding will now challenge your laptop's"
    echo -e "Face ID and Fingerprint sensors to authenticate remote sudo requests.\n"
    exit 0
fi

# -------------------------------------------------------------------------
# Auto-Clone Check (For curl | bash pipelines)
# -------------------------------------------------------------------------
if [ ! -d "${SCRIPT_DIR}/howdy" ] || [ ! -d "${SCRIPT_DIR}/src" ]; then
    echo ">>> Running from remote pipe. Cloning latest repository..."
    TMP_CLONE="$(mktemp -d /tmp/reapers-oath-install.XXXXXX)"
    if ! command -v git >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y -qq git;
        elif command -v dnf >/dev/null 2>&1; then dnf install -y git;
        elif command -v pacman >/dev/null 2>&1; then pacman -Sy --needed --noconfirm git; fi
    fi
    git clone --depth 1 https://github.com/ImNotMrReaper/reapers-oath-auth.git "${TMP_CLONE}"
    SCRIPT_DIR="${TMP_CLONE}"
    trap "rm -rf '${TMP_CLONE}'" EXIT
fi

# -------------------------------------------------------------------------
# Step 1: Package Dependencies
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 1: Installing Core Dependencies...${RESET}"
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq fprintd libfprint-2-2 gcc build-essential python3-gi gir1.2-glib-2.0 zenity libnotify-bin
    apt-get install -y -qq cmake libopenblas-dev liblapack-dev python3-numpy python3-opencv python3-pip libpam-python 2>/dev/null || true
fi

# -------------------------------------------------------------------------
# Step 2: Bozorth3 Sensitivity Tuner Compilation
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 2: Compiling Optical Bozorth3 Match Tuner...${RESET}"
mkdir -p /usr/local/lib
gcc -O2 -fPIC -shared -o /usr/local/lib/libfprint_bz3_override.so "${SCRIPT_DIR}/src/libfprint_bz3_override.c" -ldl
chmod 755 /usr/local/lib/libfprint_bz3_override.so
echo -e "    ${GREEN}✓ Compiled:${RESET} /usr/local/lib/libfprint_bz3_override.so"

# -------------------------------------------------------------------------
# Step 3: Installing Howdy Face ID Engine
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 3: Installing Howdy Face ID Engine...${RESET}"
mkdir -p /lib/security/howdy /usr/local/bin
cp -r "${SCRIPT_DIR}/howdy"/* /lib/security/howdy/
chmod -R 755 /lib/security/howdy/
mkdir -p /lib/security/howdy/snapshots
chmod 777 /lib/security/howdy/snapshots

# CLI Symlinks for Face ID
for cmd in howdy howdy-scan howdy-test howdy-hud-enroll; do
    if [ -f "${SCRIPT_DIR}/bin/${cmd}" ]; then
        cp "${SCRIPT_DIR}/bin/${cmd}" "/usr/local/bin/${cmd}"
        chmod 755 "/usr/local/bin/${cmd}"
    fi
done
echo -e "    ${GREEN}✓ Installed:${RESET} Howdy Face ID core & diagnostic HUD tools"

# -------------------------------------------------------------------------
# Step 4: Installing Fingerprint Engine & SSH Biometric Hook
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 4: Installing Fingerprint Engine & Remote SSH Hook...${RESET}"
mkdir -p /lib/security /usr/lib/openssh

# Reaper CLI
cp "${SCRIPT_DIR}/bin/reaper-auth" /usr/local/bin/reaper-auth
chmod 755 /usr/local/bin/reaper-auth

# Fingerprint Manager & Multi-Device daemon
cp "${SCRIPT_DIR}/bin/reaper-fprint-auth" /usr/local/bin/reaper-fprint-auth
chmod 755 /usr/local/bin/reaper-fprint-auth
rm -f /usr/local/bin/dp-auth
ln -sf /usr/local/bin/reaper-fprint-auth /usr/local/bin/dp-auth

cp "${SCRIPT_DIR}/bin/reaper-fingerprint" /usr/local/bin/reaper-fingerprint
chmod 755 /usr/local/bin/reaper-fingerprint
rm -f /usr/local/bin/dp-fingerprint
ln -sf /usr/local/bin/reaper-fingerprint /usr/local/bin/dp-fingerprint

# SSH Askpass hook
cp "${SCRIPT_DIR}/bin/reaper-ssh-askpass" /usr/local/bin/reaper-ssh-askpass
chmod 755 /usr/local/bin/reaper-ssh-askpass
rm -f /usr/lib/openssh/ssh-askpass /usr/bin/ssh-askpass
ln -sf /usr/local/bin/reaper-ssh-askpass /usr/lib/openssh/ssh-askpass
ln -sf /usr/local/bin/reaper-ssh-askpass /usr/bin/ssh-askpass

# PAM Module
cp "${SCRIPT_DIR}/pam/reaper_fprint_pam.py" /lib/security/reaper_fprint_pam.py
chmod 644 /lib/security/reaper_fprint_pam.py
rm -f /lib/security/dp_fprint_pam.py
ln -sf /lib/security/reaper_fprint_pam.py /lib/security/dp_fprint_pam.py

echo -e "    ${GREEN}✓ Installed CLI:${RESET} reaper-auth, reaper-fprint-auth, reaper-fingerprint"
echo -e "    ${GREEN}✓ Installed Askpass:${RESET} reaper-ssh-askpass -> /usr/lib/openssh/ssh-askpass"

# -------------------------------------------------------------------------
# Step 5: Master Access Hierarchy Configuration (Aliases & Permissions)
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 5: Configuring Access Hierarchies & User Permissions...${RESET}"
mkdir -p /etc/reaper-biometrics
if [ -f "${SCRIPT_DIR}/config/aliases.json" ] && [ ! -f "/etc/reaper-biometrics/aliases.json" ]; then
    cp "${SCRIPT_DIR}/config/aliases.json" /etc/reaper-biometrics/aliases.json
    chmod 644 /etc/reaper-biometrics/aliases.json
    echo -e "    ${GREEN}✓ Installed default access hierarchies:${RESET} Level 1 Owner (mr-reaper) + Level 2 Partner (rinnythepooh)"
else
    echo -e "    ${YELLOW}ℹ️  Preserved existing /etc/reaper-biometrics/aliases.json${RESET}"
fi

# -------------------------------------------------------------------------
# Step 6: Systemd Overrides & Shell Integration
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 6: Configuring Systemd Overrides & Shell Hooks...${RESET}"
mkdir -p /etc/systemd/system/fprintd.service.d
cp "${SCRIPT_DIR}/systemd/fprintd-override.conf" /etc/systemd/system/fprintd.service.d/override.conf
chmod 644 /etc/systemd/system/fprintd.service.d/override.conf
systemctl daemon-reload
systemctl restart fprintd || true
echo -e "    ${GREEN}✓ fprintd armed with Bozorth3 sensitivity override${RESET}"

if [ -n "$TARGET_HOME" ] && [ -d "$TARGET_HOME" ]; then
    SSH_AGENT_DIR="${TARGET_HOME}/.config/systemd/user/ssh-agent.service.d"
    mkdir -p "$SSH_AGENT_DIR"
    cp "${SCRIPT_DIR}/systemd/ssh-agent-override.conf" "${SSH_AGENT_DIR}/override.conf"
    chown -R "$TARGET_USER:$TARGET_USER" "${TARGET_HOME}/.config/systemd" 2>/dev/null || true

    if [ -f "${TARGET_HOME}/.bashrc" ]; then
        sed -i '/ssh-biometric-askpass/d' "${TARGET_HOME}/.bashrc"
        if ! grep -q "reaper-ssh-askpass" "${TARGET_HOME}/.bashrc"; then
            cat << 'EOF' >> "${TARGET_HOME}/.bashrc"

# Reaper's Oath Auth Engine: Sovereign Biometric SSH Agent Integration
export SSH_AUTH_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/openssh_agent"
export SSH_ASKPASS="/usr/local/bin/reaper-ssh-askpass"
export SSH_ASKPASS_REQUIRE="prefer"
if [ -n "$SSH_AUTH_SOCK" ] && [ -S "$SSH_AUTH_SOCK" ]; then
    if ! ssh-add -l 2>/dev/null | grep -q "id_ed25519"; then
        ssh-add -c "$HOME/.ssh/id_ed25519" 2>/dev/null
    fi
fi
EOF
        fi
    fi
    echo -e "    ${GREEN}✓ Configured user ssh-agent service override and shell hook${RESET}"
fi

# -------------------------------------------------------------------------
# Step 7: Master PAM Stack Pipeline
# -------------------------------------------------------------------------
echo -e "\n${BLUE}>>> Step 7: Configuring Sovereign Multi-Tier PAM Stack...${RESET}"
configure_pam_stack() {
    local target="$1"
    local has_howdy="$2"
    if [ -f "$target" ]; then
        # Check if already configured
        if ! grep -q "reaper_fprint_pam.py\|howdy/pam.py" "$target"; then
            cp "$target" "${target}.bak-reaper-auth"
            # Insert Face ID then Fingerprint before pam_unix
            if [ "$has_howdy" = "true" ]; then
                sed -i '/pam_unix\.so/i auth\tsufficient\tpam_python.so /lib/security/howdy/pam.py' "$target"
            fi
            sed -i '/pam_unix\.so/i auth\tsufficient\tpam_python.so /lib/security/reaper_fprint_pam.py' "$target"
            echo -e "    ${GREEN}✓ Updated:${RESET} ${target}"
        else
            echo -e "    ${YELLOW}ℹ️  Already configured:${RESET} ${target}"
        fi
    fi
}

configure_pam_stack "/etc/pam.d/sudo" "true"
configure_pam_stack "/etc/pam.d/polkit-1" "true"
configure_pam_stack "/etc/pam.d/gdm-password" "true"
configure_pam_stack "/etc/pam.d/common-auth" "false"

echo -e "\n${GREEN}================================================================${RESET}"
echo -e "${GREEN} 🎉 REAPER'S OATH AUTH ENGINE ARMED & OPERATIONAL!${RESET}"
echo -e "${GREEN}================================================================${RESET}"
echo -e "  • ${BOLD}Face ID (Howdy)${RESET}          : Enabled (128-D ResNet Vector match + 1s dark shutter fallback)"
echo -e "  • ${BOLD}Multi-Fingerprint${RESET}        : Enabled (Bozorth3 14/40 sensitivity on Optical + Goodix)"
echo -e "  • ${BOLD}Access Hierarchies${RESET}       : Level 1 Owner (mr-reaper) | Level 2 Partner (rinnythepooh)"
echo -e "  • ${BOLD}Remote SSH Biometrics${RESET}    : Enabled (/usr/local/bin/reaper-ssh-askpass)"
echo -e "\n${CYAN}Management Commands:${RESET}"
echo -e "  \033[1;35mreaper-auth status\033[0m       - Inspect all subsystems and driver health"
echo -e "  \033[1;35mreaper-auth users\033[0m        - List all registered identities and access levels"
echo -e "  \033[1;35mreaper-auth add-user\033[0m     - Interactive wizard to add a new person"
echo -e "  \033[1;35mreaper-auth test\033[0m         - Test live biometric verification"
echo -e "  \033[1;35mhowdy test\033[0m               - Launch real-time face identification HUD\n"
