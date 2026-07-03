#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skx — Skill X-ray
跨 agent 的 AI 技能审计 + 精选管控工具（零依赖，单文件）

  skx audit             机器体检：宿主、技能、context 成本、重复、坏链、bin 撞名
  skx audit --md        输出 Markdown 体检报告（可分享）
  skx audit --json      输出 JSON（供脚本/CI 用）
  skx ls                列出各宿主已装技能
  skx curate --init     从当前状态生成精选档案 profile.json
  skx curate            显示 profile 与现状的差异（干跑）
  skx curate --apply    应用 profile（增/删软链）
  skx update            git pull 所有共享仓库并报告新增/变更技能
  skx update --apply    更新后按 profile 重新对齐软链
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

VERSION = "0.1.0"

HOME = Path.home()
# 单一真源目录与 profile 位置均可用环境变量覆盖
SHARED = Path(os.environ.get("SKX_SHARED", str(HOME / "agent-shared")))
PROFILE_PATH = Path(os.environ.get("SKX_PROFILE", str(SHARED / "profile.json")))

# 候选宿主：存在 skills 目录即视为已安装
HOST_CANDIDATES = {
    "claude": HOME / ".claude" / "skills",
    "codex": HOME / ".codex" / "skills",
    "cursor": HOME / ".cursor" / "skills",
    "windsurf": HOME / ".windsurf" / "skills",
    "gemini": HOME / ".gemini" / "skills",
    "trae": HOME / ".trae" / "skills",
    "opencode": HOME / ".opencode" / "skills",
}

SYSTEM_BIN_DIRS = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
USER_BIN_DIRS = [HOME / ".local" / "bin"]

C = {
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "cyan": "\033[36m", "dim": "\033[2m", "bold": "\033[1m", "off": "\033[0m",
}
def col(s, c):
    if not sys.stdout.isatty():
        return s
    return f"{C[c]}{s}{C['off']}"


# ---------- 解析 ----------

def parse_frontmatter(skill_md: Path):
    """极简 YAML frontmatter 解析：只取 name / description，容忍多行 description。"""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return {"name": None, "description": ""}
    lines = text.split("\n")
    fm, i = [], 1
    while i < len(lines) and lines[i].strip() != "---":
        fm.append(lines[i])
        i += 1
    name, desc, in_desc = None, [], False
    for ln in fm:
        top = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if top:
            key, val = top.group(1), top.group(2)
            in_desc = False
            if key == "name":
                name = val.strip().strip("'\"")
            elif key == "description":
                in_desc = True
                if val.strip() and val.strip() not in ("|", ">", "|-", ">-"):
                    desc.append(val.strip())
        elif in_desc and (ln.startswith(" ") or ln.startswith("\t")):
            desc.append(ln.strip())
    return {"name": name, "description": " ".join(desc)}


def est_tokens(text: str) -> int:
    """粗估 token：CJK ≈ 1字/词元，其余 ≈ 4字符/词元。标注为估算值。"""
    cjk = sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))
    rest = len(text) - cjk
    return cjk + max(0, rest // 4)


def scan_host(skills_dir: Path):
    """扫描一个宿主 skills 目录，返回技能条目列表。"""
    entries = []
    if not skills_dir.is_dir():
        return entries
    for p in sorted(skills_dir.iterdir()):
        if p.name.startswith("."):
            continue
        e = {
            "link_name": p.name, "path": str(p),
            "is_symlink": p.is_symlink(), "broken": False,
            "target": None, "fm_name": None, "description": "",
            "desc_tokens": 0, "managed": False, "no_skill_md": False,
        }
        if p.is_symlink():
            target = Path(os.path.realpath(p))
            e["target"] = str(target)
            if not target.exists():
                e["broken"] = True
                entries.append(e)
                continue
            e["managed"] = str(target).startswith(str(SHARED))
        skill_md = Path(os.path.realpath(p)) / "SKILL.md"
        if skill_md.is_file():
            fm = parse_frontmatter(skill_md) or {}
            e["fm_name"] = fm.get("name")
            e["description"] = fm.get("description", "")
            e["desc_tokens"] = est_tokens(e["description"])
        else:
            e["no_skill_md"] = True
        entries.append(e)
    return entries


def scan_sources():
    """扫描共享真源：agent-shared/skills/* 与 agent-shared/repos/*/skills/*"""
    sources = {}  # fm_name -> {path, repo}
    roots = []
    direct = SHARED / "skills"
    if direct.is_dir():
        roots.append((direct, None))
    repos = SHARED / "repos"
    if repos.is_dir():
        for r in sorted(repos.iterdir()):
            sk = r / "skills"
            if sk.is_dir():
                roots.append((sk, r.name))
    for root, repo in roots:
        for p in sorted(root.iterdir()):
            if not p.is_dir() or p.name.startswith("."):
                continue
            md = p / "SKILL.md"
            if not md.is_file():
                continue
            fm = parse_frontmatter(md) or {}
            name = fm.get("name") or p.name
            if name in sources:
                sources[name]["dup_with"] = sources[name].get("dup_with", []) + [str(p)]
            else:
                sources[name] = {"path": str(p), "repo": repo,
                                 "description": fm.get("description", "")}
    return sources


def detect_hosts():
    return {n: d for n, d in HOST_CANDIDATES.items() if d.is_dir()}


def bin_shadow_check():
    """用户 bin 目录里是否有文件遮蔽系统命令（make 事件防复发）。"""
    system_names = set()
    for d in SYSTEM_BIN_DIRS:
        try:
            system_names.update(os.listdir(d))
        except OSError:
            pass
    shadows = []
    npm_bin = None
    try:
        npm_prefix = subprocess.run(["npm", "prefix", "-g"], capture_output=True,
                                    text=True, timeout=10).stdout.strip()
        if npm_prefix:
            npm_bin = Path(npm_prefix) / "bin"
    except Exception:
        pass
    for d in USER_BIN_DIRS + ([npm_bin] if npm_bin else []):
        if not d or not Path(d).is_dir():
            continue
        for f in os.listdir(d):
            if f in system_names and f != "python3":
                shadows.append({"name": f, "dir": str(d)})
    return shadows


# ---------- audit ----------

def build_report():
    hosts = detect_hosts()
    sources = scan_sources()
    report = {"hosts": {}, "sources": sources, "issues": [], "stats": {}}
    linked_names = set()

    for hname, hdir in hosts.items():
        entries = scan_host(hdir)
        report["hosts"][hname] = {"dir": str(hdir), "skills": entries}
        seen = {}
        for e in entries:
            linked_names.add(e["fm_name"] or e["link_name"])
            if e["broken"]:
                report["issues"].append(
                    {"level": "error", "host": hname,
                     "msg": f"坏链: {e['link_name']} -> {e['target']}"})
                continue
            if e["no_skill_md"]:
                report["issues"].append(
                    {"level": "error", "host": hname,
                     "msg": f"无 SKILL.md: {e['link_name']}"})
                continue
            if e["fm_name"] and e["fm_name"] != e["link_name"]:
                report["issues"].append(
                    {"level": "warn", "host": hname,
                     "msg": f"名称不一致: 目录/链接名 {e['link_name']} ≠ frontmatter {e['fm_name']}"})
            if not e["description"]:
                report["issues"].append(
                    {"level": "warn", "host": hname,
                     "msg": f"description 为空: {e['link_name']}（无法被正确触发）"})
            elif len(e["description"]) > 900:
                report["issues"].append(
                    {"level": "warn", "host": hname,
                     "msg": f"description 过长({len(e['description'])} 字符): {e['link_name']}，每次会话都要付这笔 context 税"})
            key = e["fm_name"] or e["link_name"]
            if key in seen and os.path.realpath(e["path"]) != seen[key]:
                report["issues"].append(
                    {"level": "error", "host": hname,
                     "msg": f"同名冲突: {key} 有两个不同来源"})
            seen[key] = os.path.realpath(e["path"])

    # 孤儿源：在共享真源里但没被任何宿主链接
    for name, s in sources.items():
        real = os.path.realpath(s["path"])
        used = any(
            os.path.realpath(e["path"]) == real
            for h in report["hosts"].values() for e in h["skills"]
            if not e["broken"])
        s["orphan"] = not used
        if s.get("dup_with"):
            report["issues"].append(
                {"level": "warn", "host": "sources",
                 "msg": f"真源重名: {name} 同时在 {s['path']} 与 {s['dup_with']}"})

    # bin 遮蔽
    for sh in bin_shadow_check():
        report["issues"].append(
            {"level": "error", "host": "PATH",
             "msg": f"bin 遮蔽系统命令: {sh['dir']}/{sh['name']} 会盖住 {sh['name']}"})

    # 仓库状态
    repos_dir = SHARED / "repos"
    repo_info = []
    if repos_dir.is_dir():
        for r in sorted(repos_dir.iterdir()):
            if not (r / ".git").exists():
                continue
            try:
                date = subprocess.run(
                    ["git", "-C", str(r), "log", "-1", "--format=%cs"],
                    capture_output=True, text=True, timeout=10).stdout.strip()
            except Exception:
                date = "?"
            repo_info.append({"repo": r.name, "last_commit": date})
    report["repos"] = repo_info

    # 统计
    for hname, h in report["hosts"].items():
        alive = [e for e in h["skills"] if not e["broken"] and not e["no_skill_md"]]
        report["stats"][hname] = {
            "count": len(alive),
            "desc_tokens_est": sum(e["desc_tokens"] for e in alive),
            "heaviest": sorted(alive, key=lambda e: -e["desc_tokens"])[:5],
        }
    return report


def print_audit(report, as_md=False):
    out = []
    w = out.append
    if as_md:
        w("# skx 技能体检报告\n")
    else:
        w(col("━━ skx · Skill X-ray 体检报告 ━━", "bold"))

    for hname, st in report["stats"].items():
        head = f"{hname}: {st['count']} 个技能，description 合计 ≈ {st['desc_tokens_est']} tokens/会话"
        w(("## " + head) if as_md else col("\n" + head, "cyan"))
        for e in st["heaviest"]:
            line = f"  - {e['fm_name'] or e['link_name']}: ~{e['desc_tokens']} tokens"
            w(line)

    orphans = [n for n, s in report["sources"].items() if s.get("orphan")]
    if orphans:
        head = f"未被任何宿主使用的真源技能 ({len(orphans)})"
        w(("\n## " + head) if as_md else col("\n" + head, "dim"))
        for n in orphans:
            w(f"  - {n}  ({report['sources'][n]['repo'] or 'local'})")

    if report["repos"]:
        w(("\n## 共享仓库") if as_md else col("\n共享仓库", "cyan"))
        for r in report["repos"]:
            w(f"  - {r['repo']}  最后提交: {r['last_commit']}")

    errs = [i for i in report["issues"] if i["level"] == "error"]
    warns = [i for i in report["issues"] if i["level"] == "warn"]
    head = f"问题: {len(errs)} 个错误 / {len(warns)} 个提醒"
    w(("\n## " + head) if as_md else col("\n" + head, "bold"))
    for i in errs:
        w(("- ❌ " if as_md else col("  ✗ ", "red")) + f"[{i['host']}] {i['msg']}")
    for i in warns:
        w(("- ⚠️ " if as_md else col("  ! ", "yellow")) + f"[{i['host']}] {i['msg']}")
    if not report["issues"]:
        w("  ✓ 没发现问题" if not as_md else "- ✅ 没发现问题")

    total = sum(s["desc_tokens_est"] for s in report["stats"].values())
    tail = f"\n合计 context 税(估算): ~{total} tokens/会话 · 数字为估算值,量级可信"
    w(tail if not as_md else tail + "\n\n---\n*Generated by skx · Skill X-ray*")
    print("\n".join(out))


# ---------- curate ----------

def load_profile():
    if not PROFILE_PATH.is_file():
        return None
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def curate_init(report):
    prof = {"$schema": "skx-profile-v1", "hosts": {}}
    for hname, h in report["hosts"].items():
        names = sorted(
            (e["fm_name"] or e["link_name"])
            for e in h["skills"]
            if e["managed"] and not e["broken"] and not e["no_skill_md"])
        prof["hosts"][hname] = {"dir": h["dir"], "skills": names}
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"profile 已生成: {PROFILE_PATH}")
    for hname, hc in prof["hosts"].items():
        print(f"  {hname}: {len(hc['skills'])} 个受管技能")


def curate_plan(report, profile):
    """返回 (to_add, to_remove) 列表: (host, name, source_path/link_path)"""
    sources = report["sources"]
    to_add, to_remove, missing = [], [], []
    for hname, hc in profile.get("hosts", {}).items():
        hdir = Path(os.path.expanduser(hc["dir"]))
        want = set(hc.get("skills", []))
        cur = {}
        if hname in report["hosts"]:
            for e in report["hosts"][hname]["skills"]:
                if e["managed"]:
                    cur[e["fm_name"] or e["link_name"]] = e
        for name in sorted(want - set(cur)):
            if name in sources:
                to_add.append((hname, name, sources[name]["path"], hdir))
            else:
                missing.append((hname, name))
        for name in sorted(set(cur) - want):
            to_remove.append((hname, name, cur[name]["path"]))
    return to_add, to_remove, missing


def curate(apply=False):
    report = build_report()
    profile = load_profile()
    if profile is None:
        print("没有 profile。先跑: skx curate --init")
        return 1
    to_add, to_remove, missing = curate_plan(report, profile)
    if not to_add and not to_remove and not missing:
        print("✓ 现状与 profile 一致，无需变更")
        return 0
    for h, n, src, hdir in to_add:
        print(col(f"  + [{h}] {n}  <- {src}", "green"))
    for h, n, path in to_remove:
        print(col(f"  - [{h}] {n}  (删软链 {path})", "red"))
    for h, n in missing:
        print(col(f"  ? [{h}] {n}  profile 里有但真源找不到", "yellow"))
    if not apply:
        print("\n干跑模式。执行请加 --apply")
        return 0
    for h, n, src, hdir in to_add:
        dest = hdir / n
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src)
    for h, n, path in to_remove:
        p = Path(path)
        if p.is_symlink():
            p.unlink()
    print(f"\n✓ 已应用: +{len(to_add)} / -{len(to_remove)}")
    return 0


# ---------- update ----------

def update(apply=False):
    repos_dir = SHARED / "repos"
    if not repos_dir.is_dir():
        print("没有共享仓库目录")
        return 0
    before = scan_sources()
    for r in sorted(repos_dir.iterdir()):
        if not (r / ".git").exists():
            continue
        old = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        res = subprocess.run(["git", "-C", str(r), "pull", "--ff-only", "-q"],
                             capture_output=True, text=True, timeout=120)
        new = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        if res.returncode != 0:
            print(col(f"  ✗ {r.name}: pull 失败 — {res.stderr.strip()[:120]}", "red"))
        elif old == new:
            print(col(f"  = {r.name}: 无更新", "dim"))
        else:
            n = subprocess.run(
                ["git", "-C", str(r), "rev-list", "--count", f"{old}..{new}"],
                capture_output=True, text=True).stdout.strip()
            print(col(f"  ↑ {r.name}: 更新了 {n} 个提交", "green"))
    after = scan_sources()
    new_skills = sorted(set(after) - set(before))
    gone_skills = sorted(set(before) - set(after))
    if new_skills:
        print(col(f"\n新增技能(未入 profile): {', '.join(new_skills)}", "cyan"))
    if gone_skills:
        print(col(f"上游删除的技能: {', '.join(gone_skills)}", "yellow"))
    if apply:
        print("\n按 profile 重新对齐:")
        return curate(apply=True)
    elif new_skills or gone_skills:
        print("跑 skx curate 查看对软链的影响")
    return 0


# ---------- main ----------

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "audit"
    if cmd == "audit":
        report = build_report()
        if "--json" in args:
            slim = {k: v for k, v in report.items()}
            print(json.dumps(slim, ensure_ascii=False, indent=2, default=str))
        else:
            print_audit(report, as_md="--md" in args)
    elif cmd == "ls":
        report = build_report()
        for hname, h in report["hosts"].items():
            print(col(f"{hname} ({len(h['skills'])})", "cyan"))
            for e in h["skills"]:
                mark = "⛓" if e["managed"] else " "
                bad = col(" [坏链]", "red") if e["broken"] else ""
                print(f"  {mark} {e['fm_name'] or e['link_name']}{bad}")
    elif cmd == "curate":
        if "--init" in args:
            curate_init(build_report())
        else:
            sys.exit(curate(apply="--apply" in args))
    elif cmd == "update":
        sys.exit(update(apply="--apply" in args))
    elif cmd in ("--version", "version"):
        print(f"skx {VERSION}")
    else:
        print(__doc__)
        sys.exit(0 if cmd in ("-h", "--help", "help") else 1)


if __name__ == "__main__":
    main()
