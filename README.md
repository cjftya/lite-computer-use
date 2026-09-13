# Lite Computer Use

Lite Computer Use is a small Windows desktop-control skill for Claude Code, Gemini CLI, and Codex CLI. The host model interprets natural-language requests and screenshots; a local Python command performs only explicit mouse, keyboard, window, app, file, URL, screenshot, and clipboard actions.

It is intentionally not a full autonomous computer-use system. There is no browser DOM integration, Playwright, Selenium, OCR engine, accessibility-tree crawler, app-specific automation framework, or background workflow engine.

## Current scope

- Capture the desktop or active window.
- Click, double-click, scroll, type Unicode text, press keys, and send hotkeys.
- List, inspect, and focus top-level windows.
- Launch registered apps and open normal documents or HTTP(S) URLs.
- Find files under Desktop, Downloads, and Documents, newest first.
- Read and set text clipboard content when explicitly needed.
- Return one machine-readable JSON result per invocation.
- Serialize actions so multiple agents cannot drive the desktop simultaneously.

The first release targets an interactive Windows 11 desktop. Linux, macOS, headless sessions, services, and unattended scheduled work are outside v1.

## Setup

Install Python 3.11 or later on Windows, then run:

```powershell
git clone https://github.com/cjftya/lite-computer-use.git
cd lite-computer-use
py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

Check the configuration without moving the mouse or opening an app:

```powershell
.venv\Scripts\python scripts\lcu_tools.py list_apps
```

Runtime screenshots are written to `%TEMP%\LiteComputerUse\screenshots` and cleaned after 24 hours. Redacted action logs are written to `%LOCALAPPDATA%\LiteComputerUse\logs\actions.jsonl`. Typed text, clipboard text, full paths, and full URLs are not recorded in the action log.

## Agent discovery

Start the CLI from this repository. The checked-in adapters make the skill discoverable in these workspace locations:

| Host | Workspace skill path |
|---|---|
| Codex CLI | `.agents/skills/lite-computer-use/SKILL.md` |
| Gemini CLI | `.agents/skills/lite-computer-use/SKILL.md` |
| Claude Code | `.claude/skills/lite-computer-use/SKILL.md` |

The repository-root `SKILL.md` is the canonical instruction file. Both adapters point the host back to it so the safety and execution rules stay in one place.

See the current discovery rules in the official [Codex skill documentation](https://learn.chatgpt.com/docs/build-skills), [Gemini CLI skill documentation](https://geminicli.com/docs/cli/skills/), and [Claude Code skill documentation](https://code.claude.com/docs/en/skills).

For use from every project, install or link this repository as a personal skill using the host's normal skill-management command. Keep the full repository together; `SKILL.md` depends on the bundled `scripts/` and `config/` directories.

## Command examples

Every invocation prints a single JSON object. An expected failure also uses JSON and exits with code `2`; an unexpected failure exits with code `3`.

```powershell
# Observe
python scripts\lcu_tools.py screenshot
python scripts\lcu_tools.py screenshot --active-window --delay 1
python scripts\lcu_tools.py get_active_window
python scripts\lcu_tools.py list_windows

# Act
python scripts\lcu_tools.py launch_app chrome
python scripts\lcu_tools.py focus_window "Chrome"
python scripts\lcu_tools.py open_url "https://www.naver.com"
python scripts\lcu_tools.py click 900 520
python scripts\lcu_tools.py type_text "OpenAI 테스트"
python scripts\lcu_tools.py hotkey CTRL L

# Find and open
python scripts\lcu_tools.py find_file "contract" --limit 10
python scripts\lcu_tools.py open_file "C:\Users\me\Downloads\contract.pdf"
```

`screenshot --active-window` returns the window's screen bounds. Coordinates read directly from that cropped image should be passed with `--relative-to active-window`:

```powershell
python scripts\lcu_tools.py click 420 260 --relative-to active-window
```

Move the pointer to the upper-left corner to trigger PyAutoGUI's emergency fail-safe.

## App configuration

App aliases and trusted launch commands live in `config/apps.yaml`. `launch_app` runs only an app registered there. Add an entry rather than passing arbitrary shell commands:

```yaml
apps:
  my-app:
    aliases: [my app, 사내 프로그램]
    commands: [MyApp.exe]
```

The launcher checks `PATH`, Windows App Paths, and Windows application aliases. If an app cannot be resolved, it returns an error instead of guessing through the Start menu.

## Safety model

The primitive layer validates URLs, click bounds, input sizes, and registered app commands. `open_file` rejects executable and script formats. Semantic risk still belongs to the host agent because a coordinate click can represent anything on screen.

The skill therefore requires confirmation immediately before sending, submitting, purchasing, agreeing, deleting, overwriting, installing, or changing security/system settings. Password entry, MFA, UAC approval, CAPTCHA bypass, and security-warning bypass are prohibited.

## Development and tests

Generic configuration, file-search, logging, locking, and CLI behavior are tested on any OS. Real mouse, keyboard, screenshot, and window behavior must also be exercised on an interactive Windows machine.

```powershell
python -m unittest discover -s tests -v
python -m compileall scripts tests
```

Recommended manual smoke tests are listed in [`docs/windows-smoke-tests.md`](docs/windows-smoke-tests.md).
