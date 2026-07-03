# skx — Skill X-ray

给你电脑上的 AI 技能拍片子。一条命令，看清 Claude Code / Codex / Cursor 里装了什么、重复了什么、坏了什么、每次会话在为哪些没用的 skill 付多少 context 税。

[English →](README.en.md)

```bash
skx audit             # 机器体检：宿主、技能、context 税、坏链、bin 撞名
skx audit --md        # Markdown 体检报告（可分享）
skx ls                # 各宿主已装技能一览
skx curate --init     # 把当前状态固化成精选档案 profile.json
skx curate            # 现状 vs profile 差异（干跑）
skx curate --apply    # 一键对齐（增/删软链）
skx update            # git pull 所有技能仓库，报告上游新增/删除
skx update --apply    # 更新后自动按 profile 重新对齐
```

## 真实输出示例

```
━━ skx · Skill X-ray 体检报告 ━━

claude: 16 个技能，description 合计 ≈ 2000 tokens/会话
codex: 21 个技能，description 合计 ≈ 2639 tokens/会话

未被任何宿主使用的真源技能 (4)
  - mcp-installer  (Axhub-Skills)
  ...

问题: 1 个错误 / 0 个提醒
  ✗ [claude] 坏链: broken-test -> /nonexistent/path

指令文件(每次会话全文加载)
  claude: ≈ 441 tokens
    - ~/.claude/CLAUDE.md  ~202
    - └@ ~/.claude/RTK.md  ~239

合计 context 税(估算): ~5408 tokens/会话  = skill 描述 ~4639 + 指令文件 ~769
```

## 它检查什么

- **context 税**：每个 skill 的 description 每次会话都会进上下文。skx 估算每个宿主的总开销，列出最重的 5 个
- **指令文件**：`CLAUDE.md` / `AGENTS.md` / `GEMINI.md` / `.cursorrules` / `copilot-instructions.md` 这些文件每次会话**全文**加载。skx 逐个估算 token，自动跟随 `@import` 链，抓出断掉的 import 和过重的文件
- **坏链 / 无 SKILL.md / 空 description**：装了等于没装，还占地方
- **同名冲突 / 名称不一致**：frontmatter `name` 和目录名对不上时，触发行为不可预期
- **bin 遮蔽**：npm 全局包的 bin 撞掉系统命令（真实案例：某包注册了 `make`）
- **孤儿真源**：仓库里有但没链接到任何宿主的 skill——升级时白拉的部分

## 设计原则

- 单文件 Python，零依赖，macOS/Linux 开箱跑
- 单一真源：`~/agent-shared/skills` + `~/agent-shared/repos/*/skills`，宿主目录里只放软链
- profile 即合同：`~/agent-shared/profile.json` 声明每台宿主该有什么，`curate --apply` 负责让现实符合合同
- 不碰你手动创建的非受管 skill（非指向 agent-shared 的目录一律不动）
- 环境变量覆盖：`SKX_SHARED`（真源目录）、`SKX_PROFILE`（profile 路径）

## 安装

```bash
curl -fsSL https://raw.githubusercontent.com/coikexxx/skx/main/install.sh | sh
```

MIT 许可。审计免费，永远免费。
