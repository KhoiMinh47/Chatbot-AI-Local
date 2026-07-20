# 2026-05-19 14:50 ICT - Frontend role normalization fix

## Context

- Production-style frontend showed a Next.js client-side exception while loading chat.
- Diagnosis pointed to role values sometimes being non-string objects while render paths called `toLowerCase()`.

## Changes

- Added shared role normalization helpers in `frontend/src/utils/roles.js`.
- Normalized roles loaded from `/auth/me`, `/auth/accounts`, cached `localStorage.userRoles`, signin responses, role management modal state, `ChatInput`, and `FileManagerModal`.
- Replaced unsafe role checks such as direct `.includes()` and `.map(r => r.toLowerCase())` on untrusted role values.

## Verification

- `npm run lint`: passed with existing warnings only.
- `npm run build`: passed.
- Helper smoke test normalized string roles and object-shaped roles successfully.
- `curl -I http://localhost:3100/chat`: returned `HTTP/1.1 200 OK`.

## Runtime

- Restarted only tmux session `frontned:0.0` for this repo frontend with `PORT=3100 npm start`.
- Did not restart tmux sessions named `backend` or `frontend` because they belong to `/home/ntcai/face-reconizer/face-recognition`, not this repository.
- Backend restart was not required because the fix is frontend-only.

## Follow-up Runtime Check

- Browser console later showed `/api/v1/auth/heartbeat/ping` returning `502`.
- Runtime nginx config proxies `/api/v1/` to `host.docker.internal:9000` and frontend assets/app to `host.docker.internal:3100`.
- The RAG backend was not listening on port `9000`; started it in existing tmux session `rag-chat-code`, new window `backend`.
- Rebuilt and restarted frontend after moving `activeMode` state above the role effect to remove a client-side TDZ error (`Cannot access ... before initialization`).
- Verification after backend start:
  - `POST http://localhost:3000/api/v1/auth/heartbeat/ping`: returned `401`, proving nginx reached backend and no longer returned `502`.
  - `GET http://localhost:3000/chat`: returned `200`.
  - All current JS chunks referenced by `/chat` returned `200`.
