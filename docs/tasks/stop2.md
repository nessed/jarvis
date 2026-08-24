# Stop 2 — Meta durable token and webhook review

## Preconditions

The current Quick Tunnel callback is
`https://insulation-threatened-tip-bind.trycloudflare.com/webhook`; it was
externally verified at its protected health endpoint. It expires whenever the
tunnel/laptop stops.

## Agent staging work

1. Open the correct WhatsApp app’s App Settings → Basic screen, stopping before
   the user reveals its App Secret.
2. Open Business Settings → Users → System users. If no Business Account is
   attached, stage its free creation flow; otherwise stage a new admin system
   user, app asset assignment with full control, and durable-token creation.
3. Stage the token scope/expiry screen with
   `whatsapp_business_messaging`, `whatsapp_business_management`, and Never
   expiry, then stop before its final Generate action.
4. Return to WhatsApp → Configuration and fill the fresh callback URL and
   locally held verify token, then stop before Save for user review.

## User action, batched

- Perform login/2FA/captcha if prompted.
- Reveal and copy App Secret to local `.env` as `META_APP_SECRET`.
- Perform the final system-user/token Generate action and copy the result to
  local `.env` as `META_ACCESS_TOKEN`.
- Review the filled callback URL and verify-token fields, then click the final
  Save/Confirm action. Do not share secrets in chat.
