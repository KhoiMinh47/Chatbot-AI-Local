---
name: project-workflow
description: Project workflow rules for this repository. Use when Codex works on this repo and needs to coordinate backend, frontend, documentation, logging, planning, README, and push rules.
argument-hint: "project task"
user-invocable: true
---

# Project Workflow

Use this skill when working in this repository.

## Skills

These Codex skills are kept as top-level entries under `.codex/skills/`:

- `backend-skill`
- `frontend-skill`
- `plan-skill`
- `documentation-skill`
- `logging-skill`
- `push-code-skill`
- `readme-style`

Each skill contains its own rules directly in its `SKILL.md`.

## Usage

1. Identify the task type.
2. Read the matching top-level skill.
3. Follow that skill together with active system and developer instructions.
4. If rules conflict, follow higher-priority instructions first, then the project skill rules.
