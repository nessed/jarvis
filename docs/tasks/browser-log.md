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
