# Grok Web CLI

Browser-cookie authenticated CLI for [Grok](https://grok.com) (xAI). No API key needed.

Uses Playwright to automate a headless Chromium browser with Firefox `sso` cookies for authentication.

## Quick Start

```bash
# Install dependencies
pip install playwright
playwright install chromium

# One-time: sign in via visible browser
python grok.py --login

# Send a prompt
python grok.py "Explain quantum computing in one sentence."

# Agent-native token-efficient output (JSON pointer, ~50 tokens)
python grok.py -o /tmp/out.md "What is the meaning of life?"
# → {"ok":true,"f":"/tmp/out.md","s":450,"b":2,"m":"fast","t":2.2}

# Read the response file
cat /tmp/out.md
```

## Features

- **Zero API key**: Authenticates via browser cookies (Firefox auto-detected)
- **Agent-native output**: JSON pointer format for minimal token usage
- **Multi-turn conversations**: Persist chat state with `-c chat.json`
- **Brief mode**: `--brief` for concise responses
- **Cross-platform**: Linux, macOS, Windows (WSL supported)
- **Cookie auto-extraction**: Reads Firefox cookies automatically

## Usage

```
python grok.py [OPTIONS] [PROMPT]

Options:
  -m, --model MODEL    Model to use (default: fast)
  -c, --conv FILE      Conversation state file for multi-turn
  --new                Start fresh conversation
  -o, --output FILE    Write response to file (stdout gets JSON pointer)
  --json               Full JSON output on stdout
  --brief              Prepend "Be concise." for terse responses
  -l, --login          Open visible browser for interactive login
  -q, --quiet          Suppress stderr progress messages
  --save-auth          Re-extract cookies from Firefox profiles
```

## Authentication

Grok uses an `sso` JWT cookie for authentication. The CLI auto-extracts this from your Firefox profile.

**Supported browsers:**
- **Firefox** (primary): Auto-detected from standard profile locations
- **Chrome**: Not supported for cookie extraction (encrypted on Windows/macOS)

**Setup options:**

1. **Auto-extract** (recommended): Sign in to grok.com in Firefox, then run `python grok.py --save-auth`
2. **Interactive login**: Run `python grok.py --login` to open a visible browser for OAuth sign-in
3. **Manual**: Place Firefox `cookies.sqlite` in a directory and set `FIREFOX_PROFILE_DIR`

## Models

| Flag | Model | Availability |
|------|-------|-------------|
| `fast` (default) | Grok 4.3 Fast | Free tier |

`auto`, `expert`, and `heavy` models require a SuperGrok subscription and are not available on the free tier.

## Agent-Native Output

When using `-o FILE`, stdout returns a compact JSON pointer:

```json
{"ok":true,"f":"/tmp/out.md","s":450,"b":2,"m":"fast","t":2.2}
```

| Field | Description |
|-------|-------------|
| `f` | Path to response file |
| `s` | File size in bytes |
| `b` | Code block count |
| `m` | Model used |
| `t` | Elapsed seconds |

The caller reads the output file with standard file I/O — no token cost for the response body.

## How It Works

1. Extracts `sso`, `sso-rw`, `cf_clearance` cookies from Firefox SQLite database
2. Launches headless Chromium via Playwright
3. Injects cookies into browser context
4. Navigates to grok.com, waits for React hydration
5. Types prompt into TipTap/ProseMirror editor
6. Submits via Enter key (or clicks Submit button)
7. Waits for response completion (Stop button disappears, Copy button appears)
8. Extracts last `message-bubble` element text
9. Strips "Thought for Xs" thinking prefix and UI chrome

## Dependencies

- Python 3.9+
- [Playwright](https://playwright.dev/python/) (`pip install playwright && playwright install chromium`)

## Related

- [Grok](https://grok.com) — xAI's AI assistant
- [Official Grok CLI](https://x.ai/cli) — Full coding agent (requires OAuth)
- Build your own: [build-browser-cookie-cli](https://github.com/NousResearch/hermes-agent) skill

## License

MIT
