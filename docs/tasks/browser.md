# Wave B4: browser-console setup

## Ownership

No production repository code. Only append non-secret progress and non-secret
field values to `docs/tasks/browser-log.md`. Never type, display, copy, or log
keys, tokens, passwords, verification codes, or card data. The user performs
login, 2FA, CAPTCHAs, card entry, and every final Save/Confirm dashboard action.

## Provider keys

Navigate sequentially to the API-key flow for `console.groq.com`,
`cloud.cerebras.ai`, `aistudio.google.com` (create a new project),
`openrouter.ai`, `build.nvidia.com` (Developer Program/email verification),
`console.mistral.ai` (experiment tier), and `platform.deepseek.com` (keys page
only; billing is the user's task). Stop at each login wall, notify the user,
and, once logged in, create a key named `jarvis-router` if doing so does not
require a final dashboard confirmation; otherwise stop just before it. Tell the
user when it is visible so they paste it directly into `.env` themselves.

## Meta test-number setup

The user has an existing Meta app with a WhatsApp test number, not a verified
business number. Navigate `developers.facebook.com` → app → WhatsApp → API
Setup. Read the Phone number ID and direct the user to enter it into `.env` as
`META_PHONE_NUMBER_ID` without reproducing secrets. Add the user's recipient
number; user enters its verification code. In App Settings → Basic, reveal App
Secret only with the user watching and they copy it into `.env` as
`META_APP_SECRET`.

Set up a durable access token: `business.facebook.com` → Business settings →
Users → System users → Add (name `jarvis`, admin) → Add Assets (the app, full
control) → Generate new token with `whatsapp_business_messaging` and
`whatsapp_business_management`, expiry Never. User copies the value directly to
`.env` as `META_ACCESS_TOKEN`. If no Business Account exists, guide the user
through creating a free one first; never approve/save account changes without
their explicit final action. Leave webhook callback configuration untouched
until Wave C. Log navigation and safe field values only.
