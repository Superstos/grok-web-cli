# Grok Web CLI - Development Guide

Instructions for AI coding assistants and developers working on this repo.

## What This Is

A Playwright-based CLI for [Grok](https://grok.com) (xAI) that uses browser cookies for authentication — no API key needed.

## Architecture

```
grok.py                   # Single-file CLI (~570 lines)
  ├── find_firefox_profiles()   # Cross-platform Firefox profile discovery
  ├── extract_firefox_cookies() # SQLite cookie extraction
  ├── load_auth()               # Cookie cache + auto-extraction
  ├── grok_chat()               # Main entry: Playwright browser → response
  │   ├── setup_cookies()       # Cookie injection into browser context
  │   ├── dismiss_modals()      # Cookie consent popup handling
  │   ├── send_prompt()         # Type + submit + wait
  │   │   ├── switch_model()    # Model selector dropdown interaction
  │   │   └── extract_response() # message-bubble text extraction
  │   └── save_conv()           # Multi-turn URL persistence
  └── main()                    # CLI argument parsing + dispatch
```

## Key Design Decisions

- **Playwright over Direct HTTP**: Grok's API endpoints return Next.js SPA HTML — direct API calls don't work without proper reverse-engineering
- **Firefox over Chrome**: Chrome encrypts cookies with DPAPI (Windows) / Keychain (macOS). Firefox SQLite is readable cross-platform.
- **message-bubble selector**: Grok renders chat messages as `<div class="message-bubble">`. The last one is always the assistant response.
- **TipTap editor**: Grok uses a contenteditable `div.tiptap.ProseMirror` for input, not a standard `<textarea>`. Uses `page.keyboard.type()`.
- **Stop/Copy button detection**: Response completion is detected by "Stop" button disappearing and "Copy" button appearing.

## Response Extraction

The extraction targets `[class*="message-bubble"]` elements:
- User message = first bubble
- Assistant response = last bubble

"Thought for Xs" prefix is stripped — Grok shows a brief thinking indicator even on the Fast model.

## Multi-Turn Conversations

Grok's conversation URL changes after the first message. The CLI saves `page.url` after each turn and navigates to it on subsequent turns with `-c chat.json`.

## Platform Support

`find_firefox_profiles()` handles:
- **Linux/WSL**: `/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*`
- **macOS**: `~/Library/Application Support/Firefox/Profiles/*`
- **Windows**: `%APPDATA%/Mozilla/Firefox/Profiles/*`
- **Custom**: `FIREFOX_PROFILE_DIR` env var

## Pitfalls

- **Cookie expiry**: `sso` JWT lasts hours to days. Re-run `--save-auth` when auth fails.
- **Headless detection**: Uses `--disable-blink-features=AutomationControlled` to reduce detection.
- **Model switching**: Expert/Heavy models redirect to subscription page on free tier.
- **write_file tool**: Hermes Agent's `write_file` mangles `VAR = OTHER / "path"` patterns. Use `terminal` + heredoc or `sed` as workaround.
- **Cloudflare**: Requires `cf_clearance` cookie alongside `sso`. Firefox extraction gets both.
