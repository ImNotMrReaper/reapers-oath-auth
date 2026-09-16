# Reaper Auth Engine 🛡️

**Sovereign Multi-Tier Biometric & Remote SSH Authentication Engine for Linux**

A unified, production-grade security architecture that orchestrates **Howdy Face ID**, **Multi-Device Optical & Capacitive Fingerprints (Digital Persona U.are.U 4500 + Laptop Goodix)**, and **Remote SSH Biometric Passthrough** into a seamless, zero-password Linux experience.

---

## ⚡ Architecture Overview

The Reaper Auth Engine organizes authentication into a prioritized, non-blocking biometric pipeline:

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
                   │  Tier 2: High-Speed Face ID (Howdy)              │
                   │  128-D Euclidean Vector match / 1s shutter check │
                   └─────────────────────────┬────────────────────────┘
                                             │ (If camera closed or no match)
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

## 🚀 1-Line Quick Start

### 🖥️ 1. Workstation / Laptop Setup
Arms your workstation with Face ID, Multi-Device Fingerprints, and the SSH Biometric Hook:
```bash
curl -fsSL https://raw.githubusercontent.com/ImNotMrReaper/reaper-auth-engine/main/install.sh | sudo bash
```

### 🥧 2. Remote Server / Raspberry Pi Setup
Arms any remote headless server, Raspberry Pi, or cloud VM to challenge your laptop's biometrics for `sudo`:
```bash
curl -fsSL https://raw.githubusercontent.com/ImNotMrReaper/reaper-auth-engine/main/install.sh | sudo bash -s -- --server
```

---

## 🔐 How Remote SSH Biometrics Works

When you SSH into any server running the Reaper Auth Engine with agent forwarding enabled (`ForwardAgent yes`):
1. You run `sudo command` on the remote server.
2. The server's PAM stack sends a cryptographic signing challenge back across the SSH tunnel to your laptop.
3. Your laptop's `reaper-ssh-askpass` hook intercepts the challenge and immediately triggers **Face ID** or your **Fingerprint reader**.
4. Once verified, the challenge is signed and remote `sudo` is granted in milliseconds. No passwords ever travel across the wire, and no private keys leave your workstation.

---

## 🎮 CLI Management (`reaper-auth`)

```bash
# View comprehensive subsystem status (Sensors, Drivers, SSH Hook, PAM Stack)
reaper-auth status

# Run a live interactive verification test
reaper-auth test

# Arm current machine as an SSH biometric target server
reaper-auth setup-server
```

---

## 🧩 Modular Subsystems

* **Face ID Engine:** Uses dlib ResNet-128D embeddings, YuNet ONNX detection, and automatic camera shutter obstruction fallback.
* **Optical Fingerprint Engine:** Employs `libfprint_bz3_override.so` to dynamically lower the NIST Bozorth3 threshold from `40` to `14`, fixing the notorious match failure on optical touch prisms.
* **Multi-Device Concurrency:** Claims both internal laptop capacitive sensors (Goodix MOC) and external optical USB readers (Digital Persona U.are.U 4500) concurrently via D-Bus.

---

## 📄 License
MIT License. (c) Mr. Reaper.
