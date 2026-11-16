# Environment discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 at `C:\Users\<user>\AppData\Local\Programs\Python\Python311\python.exe`.
- At session start no virtual environment existed; planned location: repository `.venv`.
- Global packages: aiohttp 3.8.5, aiosignal 1.3.1, anaconda 0.0.1.1, async-timeout 4.0.3, attrs 23.1.0, blinker 1.9.0, certifi 2024.2.2, cffi 2.0.0, charset-normalizer 3.2.0, click 8.4.2, colorama 0.4.6, contourpy 1.2.0, cryptography 46.0.5, customtkinter 5.2.2, cycler 0.12.1, darkdetect 0.8.0, discord 2.3.2, discord.py 2.3.2, Flask 3.1.3, flatbuffers 25.12.19, fonttools 4.50.0, frozenlist 1.4.0, future 1.0.0, google-api-core 2.29.0, google-api-python-client 2.189.0, google-auth 2.48.0, google-auth-httplib2 0.3.0, google-auth-oauthlib 1.2.4, googleapis-common-protos 1.72.0, httplib2 0.31.2, idna 3.4, ImageIO 2.37.3, imageio-ffmpeg 0.6.0, itsdangerous 2.2.0, Jinja2 3.1.6, keyboard 0.13.5, kiwisolver 1.4.5, MarkupSafe 3.0.3, matplotlib 3.8.3, MouseInfo 0.1.3, mss 10.1.0, multidict 6.0.4, mutagen 1.47.0, Nuitka 1.8.2, numpy 1.26.2, oauthlib 3.3.1, onnxruntime 1.27.0, opencv-python 4.8.1.78, ordered-set 4.1.0, packaging 24.0, Panda3D 1.10.13.post1, panda3d-gltf 1.0.0, panda3d-simplepbr 0.10, pathvalidate 3.3.1, pillow 12.0.0, pip 26.1.1, piper-tts 1.4.2, proto-plus 1.27.1, protobuf 6.33.5, pyasn1 0.6.2, pyasn1_modules 0.4.2, PyAutoGUI 0.9.54, pycparser 3.0, PyDirectInput 1.0.4, pyee 11.1.0, pygame 2.6.1, PyGetWindow 0.0.9, PyMsgBox 1.0.9, pynput 1.8.1, pyparsing 3.1.2, pyperclip 1.8.2, PyQt6 6.11.0, PyQt6-Qt6 6.11.0, PyQt6_sip 13.11.1, PyRect 0.2.0, PyScreeze 0.1.30, python-dateutil 2.9.0.post0, python-ffmpeg 2.0.12, pytube 15.0.0, pytubefix 8.1.1, pytweening 1.0.7, requests 2.31.0, requests-oauthlib 2.0.0, rsa 4.9.1, screeninfo 0.8.1, setuptools 65.5.0, six 1.16.0, typing_extensions 4.11.0, uritemplate 4.2.0, urllib3 2.2.1, ursina 6.1.2, Werkzeug 3.1.8, yarl 1.9.2, yt-dlp 2026.7.4, zstandard 0.21.0. `pytest` and `python-dotenv` are absent globally.
- `.env` absent; no ballchasing, OpenAI, Anthropic, Gemini or X credential variables were present in the process environment. No values recorded.
- Ollama executable and local API are available; default `llama3.1:8b` was not present.
- HTTPS access: ballchasing.com returned 200; api.x.com returned 404 at its root (host reachable; no authenticated API call was made).
- `Register-ScheduledTask` is available. No scheduled task was installed.
- Created `.venv` and installed the project editable with development dependencies: requests 2.34.2, requests-oauthlib 2.0.0, python-dotenv 1.2.4, pyperclip 1.11.0, pytest 9.2.0 and transitive dependencies.
- Venv transitive/build packages: certifi 2026.10.23, charset-normalizer 3.5.2, colorama 0.4.6, idna 3.20, iniconfig 2.3.1, oauthlib 4.0.0, packaging 26.3, pip 23.1.2, pluggy 1.7.0, Pygments 2.21.0, setuptools 65.5.0, urllib3 2.8.0.

## M1 session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed venv packages and versions match the list above. Initial suite: 35 passed.
- `.env` absent; ballchasing, AI provider and X credential groups absent from the process environment. Values were not printed.
- Ollama executable and local API available; default `llama3.1:8b` not present. ballchasing.com returned HTTP 200 and api.x.com root returned 404 (host reachable, unauthenticated). `Register-ScheduledTask` is available. No task or post was created.

## M2 session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed packages match the venv lists above. Initial suite: 83 passed.
- `.env` absent; ballchasing, AI provider and X credential groups absent from the process environment. No credential values recorded.
- Ollama executable and API available; default `llama3.1:8b` absent. ballchasing.com returned HTTP 200; api.x.com root returned 404 (host reachable without authenticated requests). `Register-ScheduledTask` is available. No task or post created.

## M4 session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed packages match the venv lists above. Initial suite: 198 passed.
- `.env` absent; ballchasing, AI provider and X credential groups absent from the process environment. No credential values recorded.
- Ollama executable and API available; default `llama3.1:8b` absent. ballchasing.com returned HTTP 200; api.x.com root returned 404 (host reachable without authenticated requests). `Register-ScheduledTask` is available. No task or post created.

## M3 session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed packages match the venv lists above. Initial suite: 127 passed.
- `.env` absent; ballchasing, AI provider and X credential groups absent from the process environment. No credential values recorded.
- Ollama executable and API available; default `llama3.1:8b` absent. ballchasing.com returned HTTP 200; api.x.com root returned 404 (host reachable without authenticated requests). `Register-ScheduledTask` is available. No task or post created.

## M5 session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed packages match the venv lists above. Initial suite: 259 passed.
- `.env` absent; ballchasing, AI provider and X credential groups absent from the process environment. No credential values recorded.
- Ollama executable and API available; default `llama3.1:8b` absent. ballchasing.com returned HTTP 200; api.x.com root returned 404 (host reachable without authenticated requests). `Register-ScheduledTask` is available. No task or post created.

## M6 session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed packages match the venv lists above. Initial suite: 276 passed.
- `.env` absent; ballchasing, AI provider and X credential groups absent from the process environment. No credential values recorded.
- Ollama executable and API available; default `llama3.1:8b` absent. ballchasing.com returned HTTP 200; api.x.com root returned 404 (host reachable without authenticated requests). `Register-ScheduledTask` is available. No task or post created.

## Configuration session discovery (2026-10-30)

- Windows `Windows-10-10.0.26200-SP0`, Python 3.11.4, repository `.venv`; installed package versions match the venv list above. Baseline: 286 tests passed.
- `.env` absent at session start; ballchasing, AI and X credential groups absent. No values recorded.
- Ollama is installed and its local API responds; default model absent. The C: drive has approximately 75 GiB free. ballchasing.com returned HTTP 200; api.x.com root returned HTTP 404 (reachable, unauthenticated). Task Scheduler cmdlets are available.
- Configuration update: `.env` was created with blank player fields and posting disabled; subsequently the ballchasing token was found configured and its authenticated doctor check succeeded. The default Ollama model was installed, and a synthetic local recap succeeded. No credential values or real player IDs were recorded.
- Real-data smoke: all three player IDs were supplied privately and neutral aliases added. A non-posting preview with a temporary 30-day freshness override succeeded at 235 weighted characters; database unchanged. A separate 48-hour listing found no shared replay. The user's current configured freshness is 480 hours, and the previewed match falls within it. The local request timeout was set to 120 seconds after one cold-start failure. No X post was attempted.

## X failure investigation (2026-11-01)

- Windows `Windows-10-10.0.26200-SP0`; Python 3.11.4 in repository `.venv`; installed packages match the venv list above. Baseline: 288 tests passed.
- `.env` exists; ballchasing and both X credential groups are present, hosted AI keys absent. User configuration has X posting enabled and OAuth1 selected. No values or player IDs recorded or modified.
- Ollama executable/API available and configured model present. ballchasing.com returned HTTP 200, api.x.com root HTTP 404 (reachable, unauthenticated); Task Scheduler cmdlets available.
- Read-only DB inspection found a locally valid, fresh cached tweet with a confirmed post failure and no in-flight post guard; no successful posts recorded in this database. Existing logs omit the X HTTP status. No X post was attempted during investigation.
- A local OAuth1 request-preparation check succeeded without sending a request; this verifies signing only, not X authorization, permissions, or billing.

## Repeated X 403 investigation (2026-11-01)

- Windows `Windows-10-10.0.26200-SP0`, Python 3.11.4 in repository `.venv`; installed packages match the venv list above. Baseline: 299 tests passed.
- `.env` exists; ballchasing and both X credential groups present, hosted AI keys absent. X posting enabled, OAuth1 selected; no values or player IDs recorded or modified.
- Ollama API and configured model available; ballchasing.com returned HTTP 200, api.x.com root HTTP 404 (reachable, unauthenticated); Task Scheduler cmdlets available.
- User reported a second confirmed 403; prior logs store its status but not the response type. No live X request was made by the assistant.
