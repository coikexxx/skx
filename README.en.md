# skx — Skill X-ray

X-ray the AI skills installed on your machine. One command shows what's installed across Claude Code / Codex / Cursor, what's duplicated, what's broken — and how many context tokens you pay for unused skills **every single session**.

[中文说明 →](README.md)

```bash
skx audit             # health check: hosts, skills, context tax, broken links, bin shadowing
skx audit --md        # shareable Markdown report
skx ls                # skills per host
skx curate --init     # snapshot current state into profile.json
skx curate            # diff reality vs profile (dry run)
skx curate --apply    # reconcile (add/remove symlinks)
skx update            # git pull all skill repos, report upstream changes
skx update --apply    # update, then re-align links to profile
```

## Real output

```
━━ skx · Skill X-ray ━━

claude: 16 skills, descriptions ≈ 2000 tokens/session
codex: 21 skills, descriptions ≈ 2639 tokens/session

Orphan skills in shared source (4)
  - mcp-installer  (Axhub-Skills)
  ...

Issues: 1 error / 0 warnings
  ✗ [claude] broken link: broken-test -> /nonexistent/path

Total context tax (est.): ~4639 tokens/session
```

## What it checks

- **Context tax** — every skill description enters every session's context. skx estimates the total per host and names the 5 heaviest offenders
- **Broken links / missing SKILL.md / empty descriptions** — installed but useless
- **Name conflicts** — frontmatter `name` vs directory name mismatches make triggering unpredictable
- **Bin shadowing** — npm global packages that register bins colliding with system commands (real case: a package registering `make`)
- **Orphan sources** — skills in your shared repos linked to no host

## Design

- Single-file Python, zero dependencies, runs on macOS/Linux out of the box
- Single source of truth: `~/agent-shared/skills` + `~/agent-shared/repos/*/skills`; host dirs contain only symlinks
- The profile is a contract: `profile.json` declares what each host should have, `curate --apply` makes reality match
- Never touches unmanaged skills (anything not pointing into the shared dir is left alone)
- Env overrides: `SKX_SHARED`, `SKX_PROFILE`

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/coikexxx/skx/main/install.sh | sh
```

MIT.
