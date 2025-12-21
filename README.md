# OpenKeyFlow
**Free, secure and open-source text expander for Windows, macOS, and Linux**
<img width="500" height="322" alt="image" src="https://github.com/user-attachments/assets/0b5b2e0f-1b6f-47dd-9609-ff809f0ba85c" />
![Untitled video](https://github.com/user-attachments/assets/b29ec144-9a06-439b-bb69-61751eb96a90)
![Untitled video (1)](https://github.com/user-attachments/assets/b2a31e96-b284-47a7-9fc5-5bd6b69123c1)
<img width="500" height="322" alt="image" src="https://github.com/user-attachments/assets/d9600c2c-2ffe-4809-a201-dcb28397832d" />

OpenKeyFlow lets you define custom text snippets that expand automatically as you type — ideal for quick replies, IT workflows, or any repetitive plaintext. Purpose-built, lightweight, secure, and built to stay free and open for everyone. Built with Python, distributed under the GNU General Public License v3. 

Download for Windows here:
https://github.com/exoteriklabs/OpenKeyFlow/releases/download/release/OpenKeyFlow-v0.0.1.zip

Windows SHA256 Hash (OpenKeyFlow-v0.0.1.zip):
D285C00096AC355C4C81D357D5CB578BE7F044C562270241B326C0D144427AA0

---

## Features

-  **Instant text expander** — type a short trigger (e.g. `-email1`) and watch it type immediately.  
-  **Persistent storage** — saves your hotkeys and expansions in a simple JSON file.  
-  **CSV import/export** — manage or share your hotkey lists easily from a CSV.  
-  **Autostart** — run silently in your tray at login and startup.
-  **Local-only** — no network access, no data collection outside of the JSON/CSV, built with security in mind.
-  **Special Add** - use triggers for multiple lines of text (emails, signatures, code, etc.)
-  **More coming soon!**

---

## Getting Started

### Download/Run the app/.exe from the Releases folder
- You can go to the "Releases" folder directly from the GitHub repo to download whichever version you need.
- Data folder with .exe must reside in the same location.

### Requirements
- Windows 10/11, macOS, or Linux
- Python 3.10+ (if running from source)  
- Or download the pre-built `.exe` from [Releases](#)

### Running from Source
1. Install dependencies for your OS:

   ```bash
   # Windows
   python -m pip install -r requirements-windows.txt

   # Linux
   python -m pip install -r requirements-linux.txt

   # macOS
   python -m pip install -r requirements-macos.txt
   ```

2. Launch the GUI from the repository root (the folder that contains `requirements.txt`):

   ```bash
   # Console
   python openkeyflow.py

   # Module form (works same way)
   python -m app
   ```

   > **Note:** Running `python app/main.py` directly will fail because it bypasses
   > the package entry point and cannot resolve package imports.

   > **Note:** On macOS/Linux, global keyboard hooks may require accessibility
   > permissions or elevated privileges depending on your desktop environment.
   > You can override the hook backend with `OPENKEYFLOW_HOOK_BACKEND=keyboard|pynput`.
   
### How to use it:
<img width="566" height="122" alt="image" src="https://github.com/user-attachments/assets/78850a26-02e8-48ce-ae62-e8e7e212a556" />

1. Enter the hotkey you want to use at the top left corner of the app, then add the output you want. Select the add button or press the enter key to add it to your hotkey list. 

![Untitled video](https://github.com/user-attachments/assets/320d777a-143f-43a8-9bdf-d1d68c394a24)

2. After that, test it out!

<img width="234" height="130" alt="image" src="https://github.com/user-attachments/assets/8ee6c77d-4f78-4775-8cdd-326943c6d944" />

3. Ctrl + F12 will enable/disable OpenKeyFlow anytime. Closing the app window will not quit/kill the app. To completely close OpenKeyFlow, right click on the red/green dot on the systray and click "Quit".


### Why I Built This
I wanted a text expander app that was fast, secure, lightweight and open source. AutoHotKey and AutoText are fine/OK and I've used them for many years. However, I wasn't interested in using these tools for scripting or automation and just needed an app to expand plaintext for IT ticket entries and repetitive emails. Because programs like this monitor your keyboard, using AutoHotKey or AutoText became less "reassuring" to use for security reasons (AutoHotKey runs scripts, AutoText isn't open source). With all this in mind and some Python knowledge, OpenKeyFlow was born!  

### FAQ

Q: Is OpenKeyFlow safe?

A: OpenKeyFlow is designed to be an offline, local-only desktop app. It does not auto update (yet) or reach the internet. So, yes it is safe to use. That said, with it being open source, this doesn't stop "bad guys" from using this to create something malicious and then pretend to be their own keyboard expander app. It's always important to know -where- your software comes from! You will only see OpenKeyFlow on the official GitHub repo.
_____________________________________________________________
Q: Can I contribute?

A: Yes! Pull requests and feedback are welcome, please follow the GNU GPL v3 license. If you'd like to donate to the project as well, you can follow the link here:

https://buymeacoffee.com/exoteriklabs
_____________________________________________________________
Q: Will there be updates?

A: Definitely. I am one person building this and I have a full time job so updates/fixes may take longer than expected. If you have suggestions of your own, feel free to reach out! 
_____________________________________________________________

If you have any questions/comments about the project, email me at github@connormail.slmail.me.

**OpenKeyFlow is distributed under the GNU GPL v3 license and intended for lawful, ethical use only.**

© 2025 OpenKeyFlow — Made with ♥️ at ExoterikLabs