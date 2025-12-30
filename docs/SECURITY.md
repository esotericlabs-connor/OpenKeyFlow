# Security Policy

Thank you for taking the time to responsibly disclose any vulnerabilities or concerns with OpenKeyFlow. We take the security and ethical use of this software seriously.

---

## Supported Versions

| Version        | Supported? |
|----------------|------------|
| Main (latest)  | ✅ YES      |
| Older builds   | ❌ NO       |

Please always use the latest official release from GitHub.

---

## Scope of Security

OpenKeyFlow is a local-first, offline desktop app. All data is stored locally and will soon be encrypted via AES.

You can help us improve by reporting any of the following:
- Flaws in encryption or insecure file handling
- Bypass of ethical use policy / user warnings
- Hotkey abuse methods (e.g. key injection beyond scope)
- Unsandboxed inputs or file corruption bugs
- UI/UX flows that could enable malicious misuse

---

##  Reporting a Vulnerability

If you discover a vulnerability, please email:

**github@connormail.slmail.me**

We prefer responsible, coordinated disclosure.

If the issue is critical, we will:
- Patch within 7–14 days if feasible
- Credit your disclosure (unless you prefer anonymity)

---

## Security Features (Currently Implemented)

- One-time Acceptable Use popup at launch
- No external API calls or internet access during runtime
- PyInstaller used with minimal flags to avoid tampering
- (in-progress)Optional data wipe on app close
- (in-progress)AES-encrypted storage of `okf_data/` contents

---

## Known Security Limitations

- No input validation for output strings (yet) — theoretically exploitable by local users
- No runtime integrity checks (e.g., hash verification of code)
- Does not protect against clipboard hijacking or keylogging by other apps
- macOS/Linux builds are experimental and may lack equivalent hardening

---

## Future Roadmap for Security

- Harden hotkey listener against memory injection
- Add tamper checks to `okf_data/` folder
- Allow user-generated encryption passphrase
- Provide SHA256 hash for public binary releases
- Create threat model documentation

---

## THANK YOU

Security researchers, ethical hackers, and responsible testers!

---

**OpenKeyFlow is distributed under the GNU GPL v3 license and intended for lawful, ethical use only.**

© 2025 OpenKeyFlow — ExoterikLabs


