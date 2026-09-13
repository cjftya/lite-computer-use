# Lite Computer Use

Lite Computer Use is a lightweight Windows computer-use skill for host agents such as Antigravity, Gemini CLI, Claude Code, and Codex CLI. The host model interprets natural-language requests and screenshots; the bundled Python layer executes only explicit mouse, keyboard, window, app, file, URL, screenshot, and clipboard primitives.

The project deliberately has no DOM integration, Playwright, Selenium, OCR engine, accessibility-tree crawler, app-specific automation framework, autonomous agent loop, scheduler, or background workflow engine.

## Requirements

- Windows 11
- Python 3.11 or later; Python 3.13 is recommended
- An interactive desktop session
- A host agent with vision support for visually guided tasks

Check the Python installations registered with the Windows launcher:

```powershell
py -0p
py -3.13 --version
```

## Install

Clone the repository and install its dependencies into the global Python 3.13 installation. A virtual environment is not required for the intended Antigravity setup.

```powershell
git clone https://github.com/cjftya/lite-computer-use.git
cd lite-computer-use
py -3.13 -m pip install --upgrade pip
py -3.13 -m pip install -r requirements.txt
```

Verify the configuration without moving the pointer or opening an app:

```powershell
py -3.13 scripts/lcu_tools.py list_apps
```

Expected shape:

```json
{"ok":true,"action":"list_apps","result":{"apps":["chrome"]}}
```

Every invocation prints exactly one JSON object. Expected failures exit with code `2`; unexpected failures exit with code `3`.

## Install as an Antigravity global skill

Place the complete repository runtime at:

```text
C:\Users\<USER>\.gemini\antigravity\skills\lite-computer-use\
├─ SKILL.md
├─ scripts\
├─ config\
├─ docs\
├─ tests\
├─ README.md
└─ requirements.txt
```

Copy the root `SKILL.md`, `scripts`, `config`, and supporting files together. Do not copy only `.agents\skills\lite-computer-use\SKILL.md`; that file is a repository adapter and does not contain the runtime.

Fully restart Antigravity CLI after installing or updating the skill. Then use natural-language requests such as:

```text
계산기 열어서 100+400 해줘.
크롬 열고 네이버 들어가줘.
메모장 열고 "테스트 성공"이라고 입력해줘.
다운로드 폴더에서 계약서 PDF 찾아서 열어줘.
그림판 열어서 네모 하나 그려줘.
크롬을 왼쪽에 놓고 메모장을 오른쪽에 놓아줘.
```

The checked-in adapters also support repository-scoped discovery:

| Host | Workspace skill path |
|---|---|
| Codex CLI / Gemini CLI | `.agents/skills/lite-computer-use/SKILL.md` |
| Claude Code | `.claude/skills/lite-computer-use/SKILL.md` |

## Primitive examples

Run commands from the skill root so the bundled configuration is resolved independently of the host agent's working directory.

```powershell
# Observe
py -3.13 scripts/lcu_tools.py screenshot
py -3.13 scripts/lcu_tools.py screenshot --active-window --delay 1
py -3.13 scripts/lcu_tools.py screenshot --region 500 300 800 600
py -3.13 scripts/lcu_tools.py get_active_window
py -3.13 scripts/lcu_tools.py list_windows
py -3.13 scripts/lcu_tools.py get_mouse_position

# Mouse and keyboard
py -3.13 scripts/lcu_tools.py move_mouse 500 400
py -3.13 scripts/lcu_tools.py click 500 400 --button right
py -3.13 scripts/lcu_tools.py double_click 500 400
py -3.13 scripts/lcu_tools.py drag 100 100 500 500 --duration 0.7
py -3.13 scripts/lcu_tools.py scroll -5
py -3.13 scripts/lcu_tools.py type_text "OpenAI 테스트"
py -3.13 scripts/lcu_tools.py press_key TAB --count 4
py -3.13 scripts/lcu_tools.py hotkey CTRL L

# Window control and bounded waiting
py -3.13 scripts/lcu_tools.py focus_window "Chrome"
py -3.13 scripts/lcu_tools.py set_window_state "Chrome" maximize
py -3.13 scripts/lcu_tools.py set_window_bounds "Chrome" 0 0 960 1080
py -3.13 scripts/lcu_tools.py wait_for_window "Calculator" --state active --timeout 10
py -3.13 scripts/lcu_tools.py close_window "Notepad"

# Apps, web, files, and folders
py -3.13 scripts/lcu_tools.py launch_app chrome
py -3.13 scripts/lcu_tools.py open_url "https://www.naver.com"
py -3.13 scripts/lcu_tools.py find_file "contract" --limit 10
py -3.13 scripts/lcu_tools.py open_file "C:\Users\me\Downloads\contract.pdf"
py -3.13 scripts/lcu_tools.py open_folder "C:\Users\me\Downloads"
py -3.13 scripts/lcu_tools.py reveal_file "C:\Users\me\Downloads\contract.pdf"
```

`reveal_file` selects a file in Explorer without opening it. `close_window` posts a normal close request; it never force-kills the process, so the application's own unsaved-document dialog remains in control.

For coordinates obtained from an active-window screenshot, use the same cropped coordinate space:

```powershell
py -3.13 scripts/lcu_tools.py click 420 260 --relative-to active-window
py -3.13 scripts/lcu_tools.py drag 100 100 500 500 --relative-to active-window
```

Negative screen coordinates are valid on monitors located left of or above the primary monitor. Region screenshots, pointer actions, and window bounds are checked against the full Windows virtual desktop. Move the pointer to the upper-left fail-safe corner to abort a PyAutoGUI mouse or keyboard action.

## How it works

```text
Natural-language request
→ Host AI reasoning and vision
→ one Lite Computer Use primitive
→ Windows GUI
→ fresh screenshot or state verification
```

The Python layer is not an autonomous agent. The host follows an Observe → Act → Verify loop and uses deterministic actions before resorting to screenshot coordinates. `wait_for_window` is only bounded polling of one window state, with a maximum timeout of 30 seconds.

## App configuration

Trusted app aliases and launch commands live in `config/apps.yaml`. `launch_app` accepts only registered apps; there is no arbitrary command or shell-execution primitive.

```yaml
apps:
  my-app:
    aliases: [my app, 사내 프로그램]
    commands: [MyApp.exe]
```

The launcher checks `PATH`, Windows App Paths, and Windows application aliases. It returns an error rather than guessing through the Start menu.

## Safety

Within the user's request, the host may capture the screen, inspect or focus windows, launch registered apps, open normal documents or known websites, search, navigate menus, scroll, move or resize windows, perform harmless drags, open folders, and reveal files.

The host must ask immediately before a final action that sends or submits data; makes a purchase, payment, booking, or agreement; deletes data; overwrites a file; installs software; or changes security/system settings.

Password or recovery-code entry, MFA entry, UAC approval, CAPTCHA bypass, security-warning bypass, secret extraction, arbitrary shell execution, process termination, and registry modification are prohibited.

Runtime screenshots are written to `%TEMP%\LiteComputerUse\screenshots` and cleaned after 24 hours. Redacted logs are written to `%LOCALAPPDATA%\LiteComputerUse\logs\actions.jsonl`. Typed text, clipboard text, complete paths, complete URLs, and complete window titles are not logged.

## Troubleshooting

### `typing.Self` import error or `unsupported_python`

The wrong Python version is running. Lite Computer Use requires Python 3.11 or later.

```powershell
py -0p
py -3.13 --version
```

Use `py -3.13`, not an unqualified `python`, when multiple versions are installed.

### `ModuleNotFoundError`

Install dependencies into the same Python 3.13 runtime used for commands:

```powershell
py -3.13 -m pip install -r requirements.txt
```

### Antigravity cannot find the skill

Confirm that the complete runtime is under:

```text
C:\Users\<USER>\.gemini\antigravity\skills\lite-computer-use\
```

Then fully exit and restart Antigravity CLI. Test the runtime directly first:

```powershell
py -3.13 scripts/lcu_tools.py list_apps
```

## Tests

```powershell
py -3.13 -m unittest discover -s tests -v
py -3.13 -m compileall scripts tests
```

Real mouse, keyboard, screenshot, Explorer, and window behavior must also be checked on an interactive Windows desktop. Follow [`docs/windows-smoke-tests.md`](docs/windows-smoke-tests.md).
