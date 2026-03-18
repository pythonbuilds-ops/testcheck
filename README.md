---
title: PhoneAgent
emoji: "📱"
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# PhoneAgent

Autonomous AI agent for Android control with two runtimes: local ADB for desktop development, and a hosted companion-app bridge for deployment targets like Hugging Face Spaces.

## Features

- Multi-model routing through Groq for planning, execution, and vision
- Capability-aware tool registration so the agent never plans around unsupported shell or filesystem access
- Accessibility-first navigation with a structured UI tree and fallback vision analysis
- Persistent SQLite-backed long-term memory and richer episodic learning metadata
- Hosted companion mode where the phone connects outbound over WebSocket instead of requiring server-side ADB
- Same-origin frontend/backend deployment for Docker and Hugging Face Spaces

## Runtime Modes

### Local Desktop Mode

Use this for development on your machine. The Python runtime talks to your phone through local `adb`.

### Hosted Companion Mode

Use this for deployment on a remote server. The backend/frontend run as one Dockerized app, and the Android companion app connects outbound to the backend over `wss://.../ws/device/{device_id}`.

In companion mode:

- the server does not need local `adb`
- the agent sees only the capabilities the phone app actually exposes
- raw shell, APK install, and file-transfer tools stay hidden unless the active controller supports them

## Quick Start

### Prerequisites

1. Python 3.9+
2. A Groq API key
3. One of these phone connection options:
   - Local mode: `adb` installed and available on `PATH`
   - Companion mode: the Android companion app in [android-companion](./android-companion/)

### Install

```bash
pip install -r requirements.txt
```

### Set Environment

```bash
# Windows
set GROQ_API_KEY=your_api_key_here

# Linux/Mac
export GROQ_API_KEY=your_api_key_here
```

### Run Local CLI

```bash
python main.py
```

That starts the local desktop runtime for ADB-based development.

### Run Hosted/Web Runtime

```bash
python server.py
```

That starts the FastAPI server which serves the built frontend, browser WebSocket endpoints, and the companion device bridge.

## Deployment

The repository now supports same-origin deployment:

- frontend requests use `/api/...`
- browser WebSocket traffic uses `/ws/...`
- device bridge traffic uses `/ws/device/{device_id}`
- `Dockerfile` binds to `${APP_PORT:-7860}` for Hugging Face Spaces

### Environment Variables

```bash
DEVICE_MODE=local              # or companion
DEVICE_ID=phoneagent-device
DEVICE_BRIDGE_TOKEN=change-me
PHONEAGENT_DB_PATH=/data/phoneagent.db
APP_PORT=7860
```

### Hugging Face Spaces Flow

1. Deploy this repo as a Docker Space.
2. Set `DEVICE_MODE=companion`, `DEVICE_ID`, `DEVICE_BRIDGE_TOKEN`, and `GROQ_API_KEY`.
3. Use persistent storage and point `PHONEAGENT_DB_PATH` at that mounted path.
4. Install the Android companion app from [android-companion](./android-companion/).
5. In the app, enter the backend URL, device id, and token, then enable accessibility, notifications, and screenshot permissions.

## Architecture

```text
User Request
    |
    v
PhoneAgent
  |- Planner
  |- Executor
  |- Vision
  `- Memory
    |
    v
Device Controller
  |- local adb controller
  `- companion rpc controller
    |
    v
Android Phone
```

The controller layer exposes:

- a capability manifest
- an observation bundle with package/activity, accessibility XML, summary text, screenshot availability, and freshness
- controller-specific action methods while keeping the agent/tool layer stable

## Companion App

The Android companion lives in [android-companion](./android-companion/) and targets Android 11+.

It uses:

- `AccessibilityService` for UI tree access and gestures
- `MediaProjection` for screenshots
- `NotificationListenerService` for notification reads
- a foreground service with WebSocket reconnect logic

The backend treats it as a private single-user bridge secured with `DEVICE_ID` plus `DEVICE_BRIDGE_TOKEN`.

## License

MIT
