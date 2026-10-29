# ADR 0003 — How an AI client signs in to Eligo: OAuth through Clerk

- **Status:** Accepted. Proven by a spike on 2026-10-29 against the production
  Clerk instance; the MCP endpoint itself is not built yet.
- **Date:** 2026-10-29
- **Deciders:** Dmitry Fadeev
- **Decision:** An MCP client (Claude Code, claude.ai, Claude Desktop) signs in
  with **OAuth 2.1, Clerk as the authorization server, pre-registered clients
  only**. The MCP endpoint accepts only OAuth access tokens issued for its own
  URL; the REST API accepts only browser session tokens. No personal API tokens.
- **Related:** [ADR 0002](0002-user-isolation-and-access-control.md) ·
  `ARCHITECTURE.md` RULE 3 · PR #189 · `backend/CLAUDE.md` §2.1, §2.3

---

## 1. Context

Recruiters should be able to ask their own AI about their own pipeline. The
MCP server must answer three questions the REST API already answers for the
browser — which workspace, is this person admitted, what may they do — without
a second user database and without a long-lived secret a recruiter pastes
into a chat client.

The unknown was whether a token Clerk issues to a third-party client carries
the organization, since the workspace is derived from `org_id` (ADR 0002).

## 2. What the spike showed (branch `spike/mcp-oauth`, never merged)

| Question | Answer, observed |
|---|---|
| Can Clerk be the OAuth server for an MCP client? | Yes. Protected-resource metadata (RFC 9728) on our side, Clerk's authorization-server metadata on theirs, PKCE S256. |
| Does the token carry the organization? | Yes, with scope `user:org:read`: Clerk's consent screen shows an org selector and the token carries `org_id`. |
| Token shape | JWT, `typ: at+jwt`, RS256, claims `sub`, `org_id`, `client_id`, `scope`, `aud` (= the resource URL the client used), `jti`. **No `azp`.** |
| Claude Code | Works with a pre-registered **public** client and a fixed callback port. |
| claude.ai / Desktop | Works with a pre-registered **confidential** client, redirect `https://claude.ai/api/mcp/auth_callback`. |

## 3. Decision details

1. **Pre-registered clients only.** Dynamic client registration is off; Client
   ID Metadata Documents are published but not admitted. Each supported client
   is one Clerk OAuth application, so a client can be revoked on its own.
2. **Audience is enforced.** The MCP endpoint rejects a token whose `aud` is
   not its own resource URL. The spike did not enforce this and accepted a
   token minted for a different URL — the real endpoint must.
3. **The two token kinds never cross.** The REST API refuses any token with
   `typ: at+jwt` or a `client_id` claim (PR #189, verified in production).
   Without that, a token handed to an AI client was a full credential for
   every REST endpoint, writes included, because the `azp` check skips tokens
   that carry no `azp`.
4. **Admission is read, never granted.** The MCP path maps `org_id` → an
   already admitted workspace, and refuses otherwise — even with
   `ELIGO_AUTO_PROVISION_TENANTS` on.
   Admission, the `mcp` feature gate and the rate limit refuse with an MCP
   **tool error** (HTTP 200, `isError`) carrying the reason, not HTTP 403/429:
   a client shows the tool error's text to the user, while a bare 403 reads as
   "connector broken". Authentication failures stay HTTP 401, missing scope 403.
5. **Exact audience.** `aud` must equal `ELIGO_MCP_RESOURCE_URL` character for
   character (PyJWT; the SDK's own resource check is off). A connector added as
   `…/mcp/` is refused — add exactly the URL the docs give.
6. **Which clients.** Any OAuth application in our Clerk instance is accepted;
   with dynamic registration off, that is only the applications we created.
   The receipt records `client_id`, so each read is attributable to one.
7. **Changes need a human in Eligo.** AI clients get read actions first; later,
   *propose* actions that create a pending change a human confirms in the Eligo
   UI. A confirmation inside the AI client does not count: the server cannot
   tell a human's click from the model's call.

## 4. Rejected

- **Personal API tokens.** A new secret store (table, RLS, rotation, revocation
  UI) to rebuild what Clerk already does, and a long-lived bearer secret that
  ends up pasted into config files.
- **Dynamic client registration.** Anyone could register a client against the
  production instance; we would lose the per-client revocation in §3.1.
- **Accepting session tokens on `/mcp`.** A browser token is not issued to the
  AI client and carries no consent for it.

## 5. Consequences

- One Clerk OAuth application per supported client; adding ChatGPT later is a
  new application, not code.
- Clerk caches its authorization-server metadata for about four hours, so a
  settings change there is not visible immediately.
- Data a recruiter queries reaches their AI vendor. That is gated separately
  (the `mcp` workspace feature with versioned terms), not by authentication.
