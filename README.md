# Reaper's Oath Auth Engine 🛡️

**Universal Sovereign Multi-Tier Biometric & Remote SSH Authentication Suite for Linux**

Reaper's Oath is an all-in-one Linux biometric architecture combining **Howdy Face ID**, **Multi-Device Optical & Capacitive Fingerprints (Digital Persona U.are.U 4500 + Laptop Goodix MOC)**, **Multi-User Access Level Hierarchies**, and **Remote SSH Biometric Passthrough** into a unified, zero-password authentication engine.

---

## ⚡ The Sovereign Authentication Pipeline

Every authorization request (Terminal `sudo`, Polkit GUI Dialogs, GDM Login, Lockscreen, or Remote SSH) traverses an intelligent, prioritized pipeline:

```text
                                 [Authentication Trigger]
                               (Sudo, Polkit, SSH, GDM Login)
                                             │
                                             ▼
                   ┌──────────────────────────────────────────────────┐
                   │  Tier 1: Remote SSH Agent Passthrough            │
                   │  pam_ssh_agent_auth.so challenges laptop socket   │
                   └─────────────────────────┬────────────────────────┘
                                             │ (If not on SSH)
                                             ▼
                   ┌──────────────────────────────────────────────────┐
                   │  Tier 2: High-Speed Face ID (Howdy Engine)       │
                   │  128-D ResNet Vector match / 1s shutter check    │
                   └─────────────────────────┬────────────────────────┘
                                             │ (If camera closed or dark)
                                             ▼
                   ┌──────────────────────────────────────────────────┐
                   │  Tier 3: Multi-Device Concurrent Fingerprints     │
                   │  Digital Persona Optical USB + Laptop Capacitive │
                   │  Tuned Bozorth3 Sensitivity (14/40 threshold)    │
                   └─────────────────────────┬────────────────────────┘
                                             │ (If sensors timeout/absent)
                                             ▼
                   ┌──────────────────────────────────────────────────┐
                   │  Tier 4: Standard Unix Password Fallback         │
                   │  Zero lockout fail-safe                          │
                   └──────────────────────────────────────────────────┘
```

---

## 👥 Multi-User Access Level Hierarchies

Reaper's Oath allows you to enroll multiple people with granular, hardware-enforced permission tiers:

| Tier | Role | Identity | Privileges & Hardware Constraints |
|:---:|:---|:---|:---|
| 👑 **Level 1** | **Primary Owner** | `mr-reaper` | Unrestricted root authority. Full `sudo`, Polkit administrative dialogs, Face ID, and all fingerprint sensors. |
| 💖 **Level 2** | **Second in Command** | `rinnythepooh` (Rin) | High-trust partner access. Desktop login and lockscreen unlock. Sudo strictly restricted to whitelisted operational commands (`apt update`, `systemctl status`, `reboot`). Blocked from raw root shells (`bash`, `su`, `visudo`, `passwd`). |
| 👤 **Level 3** | **Limited Access** | Guest / Operator | Standard unlock privileges only. Lockscreen and desktop login via fingerprint. Sudo access completely disabled. |

---

## 🚀 1-Line Quick Installation

### 🖥️ 1. Workstation / Laptop (All-In-One Setup)
Arms your laptop with Face ID, Multi-Device Fingerprint drivers, Access Hierarchies, and the SSH Biometric Hook:
```bash
curl -fsSL https://raw.githubusercontent.com/ImNotMrReaper/reapers-oath-auth/main/install.sh | sudo bash
```

### 🥧 2. Remote Server / Raspberry Pi Setup
Arms any remote headless server, Raspberry Pi (e.g. Scythe), or cloud VM to challenge your laptop's biometrics for `sudo`:
```bash
curl -fsSL https://raw.githubusercontent.com/ImNotMrReaper/reapers-oath-auth/main/install.sh | sudo bash -s -- --server
```

---

## 🔐 Remote SSH Biometric Authentication

When you SSH into any remote server armed with Reaper's Oath:
1. You run `sudo command` on the remote server.
2. The server challenges your forwarded SSH agent socket (`ForwardAgent yes`).
3. Your workstation's `reaper-ssh-askpass` hook intercepts the challenge and immediately triggers **Face ID** or your **Fingerprint sensor**.
4. Once verified, the challenge is signed and remote `sudo` is granted in milliseconds. No passwords ever travel across the wire, and no private keys leave your workstation.

---

## 🎮 CLI Management (`reaper-auth`)

```bash
# View comprehensive subsystem status (Sensors, Drivers, SSH Hook, PAM Stack)
reaper-auth status

# View registered identities, access levels, and enrolled fingers
reaper-auth users

# Interactive wizard to add a new person and assign access levels
reaper-auth add-user

# Run live biometric verification test
reaper-auth test

# Launch real-time augmented reality Face ID HUD
howdy test
```

---

## 📄 License
MIT License. Open-source and free for personal and sovereign homelab use. (c) Mr. Reaper.
