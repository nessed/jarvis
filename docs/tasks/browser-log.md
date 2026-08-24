# Browser lane log

- Groq API Keys opened at `https://console.groq.com/keys`; sign-in is required.
- Wave C temporary callback URL is ready: `https://injured-drew-wells-partner.trycloudflare.com/webhook`. It has not been entered or saved in Meta.
- Groq sign-in completed. The Create API Key dialog is open with display name `jarvis-router` and no expiration; it is paused immediately before Submit for the user's final confirmation.
- The local `GROQ_API_KEY` entry was later confirmed present and format-valid without exposing it.
- Cerebras Cloud opened at `https://cloud.cerebras.ai/`; it is at its sign-up/log-in screen, with a cookie-preference banner visible.
- Cerebras sign-in completed. API Keys → Generate API key is open with `jarvis-router` entered, paused immediately before the user's final Create confirmation.
- The user explicitly authorized the final Cerebras Create action. The new key is revealed on screen for the user to copy directly into local `.env`; the agent did not read, copy, or store it.
- Google AI Studio: created and imported a separate `jarvis-router` Cloud project. AI Studio rejected the automated key-generation request as suspicious; no bypass was attempted. The user needs to create this one key manually in the imported project before the agent can store it locally and continue.
- Pause handoff: the user is closing the laptop. Chrome sessions may need to be reopened/reclaimed. The temporary local bus and Cloudflare Quick Tunnel stop with the laptop; regenerate a new callback URL before configuring Meta.
- 24 Aug 2026 L3 read-only reconnaissance: local FastAPI bus restarted and its protected `/health` route returned `401` locally, confirming it is running with bearer protection. Cloudflare Quick Tunnel creation could not complete: `api.trycloudflare.com` timed out after the sandbox-network retry, so there is no replacement callback URL yet.
- 24 Aug 2026 orchestrator retry: a replacement Quick Tunnel is running at `https://insulation-threatened-tip-bind.trycloudflare.com`; external protected `/health` returned `401`. Use `https://insulation-threatened-tip-bind.trycloudflare.com/webhook` for the next Meta review. This URL expires on tunnel/laptop restart.
- Meta: exactly one app has WhatsApp attached: `WA 1st` (App ID `927435833723149`; in development; Business `Slade AI`). The claimed test number is `+1 (555) 201-0561`; Phone Number ID is `1303482916173126`; WABA ID is `1522256489642825`. The dashboard currently reports no generated access token.
- Recipient allow-list: one existing Pakistani recipient number is already present; no re-verification is needed.
- Existing WhatsApp webhook configuration was inspected without changes: callback URL is a stale `ngrok-free.dev` `/webhook/whatsapp` endpoint; the verify-token field is populated and masked. `messages` is subscribed. The current app remains unpublished, and Meta warns that production data is not delivered to its webhook until publish.
