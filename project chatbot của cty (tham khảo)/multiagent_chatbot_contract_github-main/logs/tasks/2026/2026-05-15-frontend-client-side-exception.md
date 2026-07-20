# 2026-05-15 16:54 ICT - Frontend client-side exception

## Context

- User reported production page `chat.ntcai.vn` showing Next.js client-side exception screen.
- Local DNS from this workspace could not resolve `chat.ntcai.vn`, so diagnosis used repository code, local lint, and local production build.

## Findings

- `frontend` production build succeeded, so the failure is likely a browser runtime exception.
- The chat page had multiple render paths assuming `roles` is always `string[]`.
- If cached `localStorage.userRoles` or an API response contains non-string role values, calls such as `r.toLowerCase()` can throw during render and trigger the blank Next.js application error page.

## Changes

- Added `frontend/src/utils/roles.js` to normalize role values from strings and common object shapes.
- Normalized current-user roles, account-list roles, selected-user roles, and file-manager role checks before rendering.
- Guarded initial `localStorage.getItem('userId')` access.

## Verification

- `npm run lint`: passed with existing warnings only.
- `npm run build`: passed.
- Dev server started on `http://localhost:3010`.
