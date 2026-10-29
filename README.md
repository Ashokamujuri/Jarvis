<div align="center">

# 🤖 Jarvis — Personal AI Assistant

**A modular, voice-activated AI assistant for Windows — powered by Gemini & Groq LLMs**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Gemini%20%7C%20Groq-orange?style=for-the-badge&logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

*Speak to your PC. Jarvis listens, thinks, and acts.*

</div>

---

## 🌟 Overview

Jarvis is a fully local, extensible personal AI assistant that runs on Windows. It combines voice recognition, offline text-to-speech, local SQLite memory persistence, dual LLM support (Google Gemini & Groq), wake-word activation ("Hey Jarvis"), a centralized risk & permission system, and a polished desktop GUI — all in a single Python package.

---

## 🏛️ Architecture

Jarvis is built around a decoupled, layered pipeline where each subsystem operates independently:

```
                         ┌──────────────────────────┐
                         │  main.py (--gui / --cli) │
                         └─────────────┬────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │   jarvis.app  (Event Bus)   │
                        └──────┬───────────────┬──────┘
            ┌──────────────────┴───┐       ┌───┴──────────────────┐
            │                      │       │                      │
  ┌─────────▼────────┐  ┌──────────▼────┐  │  ┌──────────────────────────────────────┐
  │ Desktop GUI (Tk) │  │ Speech / Audio│  │  │ CommandProcessor  (3-Tier Routing)   │
  │ - Status badge   │  │ - WakeWord    │  │  ├──────────────────────────────────────┤
  │ - Mic indicator  │  │ - Listener    │  │  │ 1. System Commands (hello, quit…)    │
  │ - Chat history   │  │ - TTS Speaker │  │  │ 2. ToolRegistry + SafeExecutor       │
  │ - Listen toggle  │  └───────────────┘  │  │ 3. LLM Brain (Gemini / Groq)         │
  │ - Text input     │                     │  └───────────────────┬──────────────────┘
  └──────────────────┘                     │                      │
                                           │         ┌────────────▼────────────┐
                                           │         │   PermissionManager     │
                                           │         │  (SAFE/MODERATE/DANGER) │
                                           │         └────────────┬────────────┘
                                           │                      │
                                           │         ┌────────────▼────────────┐
                                           │         │     Built-in Tools      │
                                           │         │  - get_time             │
                                           │         │  - system_info          │
                                           │         │  - open_application     │
                                           │         │  - close_application    │
                                           │         │  - web search & browser │
                                           │         │  - play_music (Chrome)  │
                                           │         │  - memory (SQLite)      │
                                           │         │  - create_file          │
                                           │         └─────────────────────────┘
```

### Module Responsibilities

| Module | Location | Purpose |
|---|---|---|
| **App Orchestrator** | [`jarvis/app.py`](jarvis/app.py) | Coordinates all subsystems, manages speech/wake-word loops, exposes an event bus for UI decoupling. |
| **GUI Layer** | [`jarvis/gui/`](jarvis/gui/) | Tkinter desktop UI with status indicators, audio state, conversation history, and listening controls. |
| **Command Processor** | [`jarvis/commands/`](jarvis/commands/) | 3-tier routing: system commands → tool execution → LLM brain. |
| **Tool Framework** | [`jarvis/tools/`](jarvis/tools/) | `BaseTool`, `ToolRegistry`, and `SafeExecutor` with centralized permission checks and error containment. |
| **Permissions** | [`jarvis/permissions.py`](jarvis/permissions.py) | `RiskLevel` classifications (SAFE, MODERATE, DANGEROUS, BLOCKED) and voice confirmation callbacks. |
| **Memory Store** | [`jarvis/memory/`](jarvis/memory/) | Local SQLite persistence for user facts with CRUD operations. |
| **AI Brain** | [`jarvis/brain/`](jarvis/brain/) | Dual-provider LLM support: **Google Gemini** (`gemini_brain.py`) and **Groq** (`groq_brain.py`). |
| **Personality** | [`jarvis/personality.py`](jarvis/personality.py) | System prompt configuring character tone, speech rules, and behavior guidelines. |
| **Speech Input** | [`jarvis/speech/`](jarvis/speech/) | Microphone capture with ambient noise calibration and Google Speech Recognition. |
| **Wake Word** | [`jarvis/wakeword/`](jarvis/wakeword/) | Low-overhead phrase detection ("Hey Jarvis") with inline command extraction. |
| **Voice Output** | [`jarvis/tts/`](jarvis/tts/) | Offline Windows SAPI5 voice synthesis via `pyttsx3`. |
| **Utilities** | [`jarvis/utils/`](jarvis/utils/) | Word-boundary phrase matching, argument parsing, and ASCII console sanitization. |

---

## ✨ Features

### 🎤 Voice & Wake-Word Activation
- Say **"Hey Jarvis"** to activate — supports inline commands (e.g., *"Hey Jarvis what time is it"* executes immediately).
- Microphone ambient-noise calibration for reliable recognition.
- Seamlessly falls back to text input when no mic is available.

### 🧠 Dual LLM Brain (Gemini & Groq)
- Switch between **Google Gemini** (default: `gemini-2.5-flash`) and **Groq** (default: `qwen3.8-27b`) via `.env`.
- Multi-turn conversation context maintained across interactions.
- Falls back gracefully to built-in tools when the LLM is unavailable.

### 🖥️ Desktop Application Control
- Launch installed Windows apps by name: Chrome, VS Code, Notepad, Calculator, Paint, File Explorer, Task Manager, and more.
- Close running applications by voice or text command.
- Secure allowlist prevents arbitrary shell execution.

### 🌐 Web Search & Browser
- Open verified websites directly (YouTube, GitHub, Google Drive, Reddit, ChatGPT, etc.).
- Execute Google web searches from voice commands.
- Chrome CDP integration for advanced browser control.

### 🎵 Music Playback
- Play music on YouTube or Spotify via Chrome with smart tab reuse.
- Control playback without opening unnecessary new browser windows.

### 💾 Persistent Local Memory (SQLite)
- Store facts: *"Remember that my project is called Jarvis."*
- Recall facts: *"What do you know about Python?"*
- Search, delete individual entries, or clear all memories.
- Dynamic permission scaling — clearing all memories requires confirmation.

### 🛡️ Centralized Permission System

| Risk Level | Behavior | Example |
|---|---|---|
| `SAFE` | Runs immediately, no confirmation | Get time, system info |
| `MODERATE` | Requests voice confirmation | Open apps, clear memories |
| `DANGEROUS` | Requires explicit confirmation, auto-denied in headless mode | Destructive file ops |
| `BLOCKED` | Always denied | Blocked system operations |

### 📂 File Creation
- Create files by voice or text command with risk-aware confirmation.

### 🖼️ Desktop GUI
- Real-time status badges for all subsystems (Brain, Mic, Speech, Wake Word).
- Scrollable, timestamped conversation history with a clear control.
- Listening toggle button — start/stop Jarvis without restarting.
- Full text input for command entry without speaking.

---

## ⚠️ Known Limitations

1. **Online Speech Recognition** — Uses Google's free web API via `SpeechRecognition`, requiring internet. Offline alternatives (Vosk, Porcupine) are supported via base classes.
2. **API Rate Limits** — If the LLM provider is rate-limited, Jarvis continues operating with built-in tools and system commands.
3. **Windows Platform** — App launch paths, Windows URI schemes (`ms-settings:`), and `pyttsx3` TTS are optimized for Windows.

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.10 or later
- Windows 10/11
- A microphone (optional — text input works without one)
- A **Gemini** or **Groq** API key (optional — built-in tools work without LLM)

### 2. Installation

```powershell
# Clone the repository
git clone https://github.com/YOUR_USERNAME/jarvis.git
cd jarvis

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```powershell
# Copy the template
copy .env.example .env
```

Edit `.env` and fill in at least one API key:

```env
# Choose your LLM provider: "gemini" or "groq"
JARVIS_BRAIN_PROVIDER=gemini

# Google Gemini (https://aistudio.google.com/apikey)
GEMINI_API_KEY=your_gemini_api_key_here

# OR Groq (https://console.groq.com/keys)
GROQ_API_KEY=your_groq_api_key_here
```

### 4. Run Jarvis

```powershell
# Launch with Desktop GUI (default)
python main.py

# OR launch in CLI / terminal mode
python main.py --cli
```

> **Windows users:** You can also double-click `run_jarvis.bat` to start the GUI instantly.

---

## 🛠️ Adding a Custom Tool

All tools subclass [`BaseTool`](jarvis/tools/base.py) and declare their name, description, risk level, and trigger keywords.

### Step 1 — Create the Tool File

Create `jarvis/tools/builtins/weather.py`:

```python
from jarvis.permissions import RiskLevel
from jarvis.tools.base import BaseTool, ToolResult

class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Checks the current weather forecast."
    risk_level = RiskLevel.SAFE  # No confirmation needed
    keywords = {"weather", "forecast", "temperature", "is it raining"}

    def action_summary(self, raw_text: str) -> str:
        return "check the local weather"

    def execute(self, raw_text: str) -> ToolResult:
        # Your implementation here
        return ToolResult(
            success=True,
            message="The weather is currently clear and 72°F.",
            data={"temp": 72, "condition": "clear"}
        )
```

### Step 2 — Register the Tool

In [`jarvis/tools/builtins/__init__.py`](jarvis/tools/builtins/__init__.py):

```python
from jarvis.tools.builtins.weather import WeatherTool

def register_all(registry: ToolRegistry) -> None:
    # ... existing tools ...
    registry.register(WeatherTool())
```

Your tool is now automatically:
- Routed by the `CommandProcessor`
- Protected by `SafeExecutor` and `PermissionManager`
- Listed in the `help` command output
- Available in both GUI and CLI modes

---

## ⚙️ Configuration Reference

All settings live in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `JARVIS_BRAIN_PROVIDER` | `gemini` | LLM backend: `gemini` or `groq` |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `GROQ_API_KEY` | — | Groq API key |
| `JARVIS_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `JARVIS_GROQ_MODEL` | `qwen/qwen3.8-27b` | Groq model name |
| `JARVIS_WAKE_WORD` | `hey jarvis` | Custom wake-word phrase |
| `JARVIS_WAKE_WORD_ENABLED` | `true` | Enable/disable wake-word |
| `JARVIS_SPEECH_LANGUAGE` | `en-US` | Speech recognition language |
| `JARVIS_TTS_RATE` | `175` | TTS speaking rate (words/min) |
| `JARVIS_LOG_LEVEL` | `INFO` | Logging verbosity |

---

## 📁 Project Structure

```
jarvis/
├── main.py                  # Entry point (--gui / --cli)
├── requirements.txt         # Python dependencies
├── .env.example             # Configuration template
├── run_jarvis.bat           # Windows quick-launch script
└── jarvis/
    ├── app.py               # Core orchestrator & event bus
    ├── config.py            # Centralized config loading
    ├── personality.py       # AI character & system prompt
    ├── permissions.py       # RiskLevel & permission manager
    ├── logger.py            # Logging setup
    ├── brain/               # LLM providers (Gemini, Groq)
    ├── commands/            # 3-tier command processor
    ├── gui/                 # Tkinter desktop interface
    ├── memory/              # SQLite memory store
    ├── speech/              # Speech recognition
    ├── tts/                 # Text-to-speech
    ├── wakeword/            # Wake-word detection
    ├── tools/               # Tool framework
    │   ├── base.py          # BaseTool, ToolResult
    │   ├── registry.py      # ToolRegistry
    │   ├── executor.py      # SafeExecutor
    │   └── builtins/        # Built-in tools
    │       ├── get_time.py
    │       ├── system_info.py
    │       ├── open_app.py
    │       ├── close_app.py
    │       ├── web_search.py
    │       ├── play_music.py
    │       ├── memory.py
    │       └── create_file.py
    └── utils/               # Shared utilities
```

---

## 📄 License

This project is licensed under the **MIT License**.

---

<div align="center">
  Made with ❤️ by <strong>Ashok</strong> — <em>Built to be extended. Built to be spoken to.</em>
</div>
