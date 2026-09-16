# fresh-eyes-review

**English.** A DeepSeek Harness skill that delegates code review to a *fresh-context* subagent (provider `spawn` — an empty conversation that does **not** inherit the author's context), then forces every finding to carry a location, a reproduction command, and evidence — either inline output or a file holding the raw output with its exit code on the first line. A small programmatic gate validates the report and reports through exit codes; its `--replay` mode re-runs the reproduction commands and diffs the result against that recorded evidence. The loop closes by re-inserting the bug — the test must go red. This project does **not** claim to have invented independent review, evidence requirements, mutation closure or gates; each of those exists elsewhere and is credited below. It claims one narrow slot, states plainly what it has not solved, and welcomes counter-examples.

---

## 1. 这是什么，为什么需要它

让 AI 写完代码之后自己再读一遍，基本没有用。

原因不是模型不够聪明，而是**自审和产出用的是同一个脑子里的同一套想当然**——第一遍没看出来的地方，第二遍照样看不出来。这一点有可测量的证据：把**同一处错误**分别以"外部注入"和"模型自己产生"两种身份喂给模型，14 个模型呈现出 **64.5% 的自我纠错盲区**（能力在，但"自己错的时候"不被激活）——Tsui, *Self-Correction Bench*, arXiv:2507.02778。

这个 skill 针对的正是这条盲区，做法是三件事：

1. **换一个空对话的审查者。** 用 DSH 原生的 `subagent`（provider = `spawn`）委派。子 agent 以空对话开始，看不到作者的会话、取舍和中间推理——它被迫从产物本身重新理解一遍。
2. **强制它交证据，而不是交意见。** 每条发现必须写出「位置 + 复现命令 + 证据」；证据要么内联贴出输出，要么**落盘成文件**（首行写 `[exit code: N]`，其后是原始输出）并在报告里写明路径。给不出的条目会被门禁挡下，按噪声处理。
3. **用"把 bug 装回去"收口。** 修完一条，补一个断言，再把 bug 故意放回去——断言必须变红。红不了，说明断言没咬住。

在这三条里，第 3 条最值得优先做：它是会把资产留下来的那一条——把"有人看过"变成"机器以后一直看着"。

---

## 2. 它和其他做法的区别

这一节写得比较长，因为**如果不写清楚，本项目看起来就像在重新发明轮子**。结论先给：

> **独立审查者、证据强制、变异收口、程序化门禁——这四个零件单独都已经被别人做过，而且有些做得比本项目更深。本项目不声称发明了它们中的任何一个。**
>
> 本项目 claim 的是一个很窄的口子：**对"一份 LLM 审查报告"这个产物本身跑校验器，并按条目重放其中的证据。**
>
> 我没有找到同时做到这一点的实现。如果你知道有，请开 issue 告诉我。

### 2.1 已经做过的部分（逐项、据实）

**独立上下文的审查者** —— 已经是标配，不是差异点。

- 官方 `anthropics/claude-code` 的 `code-review` 插件结构相当正规：4 个并行 agent，并且**每一个问题都会派一个独立的验证 subagent**。但它过滤误报靠的是 **0–100 置信度打分 + 阈值（默认 80）**，而不是证据；其文档里还明确写着不要跑 linter 去验证（"Issues that a linter will catch (do not run the linter to verify)"）——即主动放弃了执行式验证。
- `momomuchu/make-no-mistakes` 用 `context: fork` 加上禁用写工具（`disallowed-tools: [Write, Edit, ...]`）做出**结构性独立**：验证者没有对话历史、也不能改文件；并且明令禁止"读到 verdict.log 是绿的就算验证过"，必须自己重跑 gate。

**证据强制** —— 有人做了，而且有人做得更狠。

- `Kappaemme-git/codex-bug-reproducer` 的 SKILL.md 原文是 *"Never claim a bug from code inspection alone"*；候选带 `file:line`，实测输出由脚本落盘成 JSON，再用另一个脚本比对修复前后，并用八态标签区分（`REPRODUCED` / `NO_BUG_PROVEN` / `FIX_UNVERIFIED` / `FIX_PROVEN` 等），不许把"未验证"含糊成"通过"。
- `andrewstellman/quality-playbook` 强制每个 bug 产出 `quality/results/BUG-NNN.red.log` 与 `.green.log`，缺失即 gate FAIL。
- `QwenLM/qwen-code` 的 autofix skill 要求：任何"当前行为是错的"的声明，必须**先复现再修**，写下失败的测试或 probe 并记录其输出。

**变异收口（把 bug 装回去必须变红）** —— 也有人做成了代码，而且是自动化的。

- `momomuchu/make-no-mistakes` 有真正的 `scripts/mutate.py`：做单点变异（`==` ↔ `!=`、`>` ↔ `>=`、`and` ↔ `or`、`True` ↔ `False`），写回源文件重跑测试；存活下来的变异体即判"测试太弱"，**kill-rate < 50% 直接 FAIL，挡死 DONE**；配套还有 10 级门禁阶梯与 `oracle_tier` 分档，且 `SKIPPED` 明确不算绿。
- `QwenLM/qwen-code` 的 autofix 有显式的 mutation probe 规则：「提交前临时移除或取反新增的 guard / branch，重跑本该抓住它的聚焦测试，确认它们 FAIL，然后恢复并回到绿」，并由 PR #9578 落地为 enforce。

**程序化门禁 + 退出码** —— 多套成熟实现。

- `vnmoorthy/groundtruth`：Claude Code 的 `Stop` hook，读到"完成声明"却在同一 turn 找不到验证痕迹时返回 `{"decision":"block"}`，并用 `audit --fail-on 1` 给 CI 退出码。
- `reviewdog/reviewdog`：把确定性 linter 结果贴回 diff 并作为状态检查。
- `PerryLink/dsh-doublecheck`（DSH 生态）：四阶段交付门禁（需求审讯 / 测试证据 / 实现一致性 / 评审结论），出 `gate-report.md` + `gate-report.json`，CLI 退出码 **0 = deliverable / 1 = rework / 2 = 用法错误**，并有 red/green 证据门。
- `QwenLM/qwen-code`：门禁会重跑本轮的确切命令，任一失败即**拒绝整轮提交**。

### 2.2 本项目 claim 的那一点

把上面这些放在一起看，会发现一个空位：

> **有人把"发现必须带证据"写成了规范或提示词，但没有一个开源工具去解析一份审查报告、按条目断言它带可执行命令与实测输出，并以退出码否决不合规的报告。**

这正是 `check_review_report.py` 做的事——它不审查代码，它**审查审查报告**。而且它不止于"字段在不在"，有三层：

1. **默认档**：字段带齐了没有、证据文件在不在、首行是不是退出码、**位置指向的文件真的存在吗**（解析 `路径:行号`，核实文件与行号范围）。
2. **`--pre-fix` 档**（动手改之前跑）：重跑每条的**反向前置**命令，**要求它仍然失败**。跑绿了就说明缺陷复现不了——先别修。
3. **`--replay` 档**（改完之后跑）：**重跑报告里的复现命令，并与审查者落盘保存的原始输出做 diff**。

第 2 层是治「命令没有证明力」的：重放只能证明"命令跑过、输出对得上"，证明不了这条命令与结论有关。要求一个「在缺陷代码上会失败」的命令、且其证据退出码必须非零，就把`assert True` 这类恒真证据变成了**硬失败**。

为什么需要重放这一层，见下一节。

### 2.3 我没有解决好的部分（这一节比上一节重要）

`quality-playbook` 的代码注释里记录了一个真实事故：**模型执行了命令，却把自己编造的"期望输出"写进了证据文件**（v1.3.19 VIRTIO_F_RING_RESET 幻觉）。这个项目因此加了一层机制：把机械取证命令的原始输出**重定向落盘**，再生成 `verify.sh` 重跑同一条命令并与落盘文件 diff，且要求必须执行。

这条事故直接否定了"报告里写了命令和输出 = 真跑过"这个假设。DSH 生态里的 `joekytc/dsh-swarm` 把同一件事写进了自己的 Known limitations：

> *"Review evidence is existence-checked, not replay-proven. Fields must be present and well-formed; proving the tests actually ran is not yet supported."*

本项目的 `--replay` 就是照 `quality-playbook` 的思路，把这个缺口往"按条目重放"的方向推了一步。但要说清楚：

- **它仍然不是证明。** `--replay` 能发现"命令跑不出报告里那个输出"，但发现不了"命令本身是精心挑选来避重就轻的"。它是筛子，不是证明器。
- **它是本仓库里最不成熟的一块。** 整套门禁现在有 42 条断言钉着，其中 8 条专门覆盖 `--replay`（输出不一致、退出码不一致、命中拒绝表、超时、易变内容归一化……）；但真正的难点在断言之外——依赖版本、并发顺序、环境差异造成的"重放不上"，目前只能靠人判断。**而且「假失败率」这个数字目前是空的**：归一化只折叠十类已知易变 token，不在表里的易变内容会让重放判"不一致"。保守是故意的，但如果假失败比例太高，人就会干脆不用 `--replay`。这个数字没有被量过之前，不要声称这一档已经"可用"。
- **它验不了「命令有没有证明力」。** 一次主动攻击实测，五种攻击姿态 × 四个档位的防线：

  | 攻击姿态 | 默认 | `--strict` | `--replay` | `--pre-fix` |
  |---|---|---|---|---|
  | 位置指向不存在的文件/行号 | ⚠️ | ✅ | ✅ | ⚠️ |
  | 跑一条与发现无关的命令 | ⚠️ | ⚠️ | ✅ | ⚠️ |
  | 证据只留输出的一行（选择性摘录） | ⚠️ | ⚠️ | ✅ | ⚠️ |
  | 恒真命令 + 证据记成 exit 0 | ✅ | ✅ | ✅ | ✅ |
  | 恒真命令 + 把前置证据伪造成 exit 1 | ⚠️ | ⚠️ | ⚠️ | ✅ |

  位置可核实性（解析 `路径:行号` → 文件存在、行号在范围内）与**反向前置**（要求给出「在缺陷代码上会失败」的命令，且其证据退出码必须非零）是后来补上的两层；`--replay` 还会重跑前置命令并要求它**已转绿**，所以它能拦下「无关命令」。

  **两个至今未解决的缺口，都必须由人判断：**
  1. **「碰巧失败的无关命令」在改前改后都失败时，只有 `--replay` 会因为「前置没转绿」拦下它**；作者真把缺陷修好、只是命令选得无关时，仍要靠人判断那个失败是否指向结论。
  2. **伪造前置证据退出码、命令却是恒真的，只有 `--pre-fix` 抓得住**（只有它会在改之前真的重跑）。所以 **`--pre-fix` 不是可选项**：只跑 `--replay` 就等于放弃了「先红」那一半。
- 如果你想看这个方向上做得更彻底的，去看 `quality-playbook` 与 `qwen-code` 的 autofix；它们分别在"防伪造"和"提交前强制"上走得比我远。

---

## 3. 安装

DSH 的 skill 就是磁盘上的一个目录，**热发现**：放进去即可，不用重启 DSH、不用装插件、不用改 profile。

```bash
git clone https://github.com/Dely0/fresh-eyes-review.git
```

然后把 **整个 `fresh-eyes-review/` 子目录**（不是单个 SKILL.md——脚本和参考资料是配套的）复制到用户级 skill 根：

```bash
# Linux / macOS
cp -r fresh-eyes-review/fresh-eyes-review ~/.dsh/skills/

# Windows (PowerShell)
Copy-Item -Recurse fresh-eyes-review\fresh-eyes-review "$env:USERPROFILE\.dsh\skills\"
```

放在用户级（`$DSH_HOME/skills`，默认 `~/.dsh/skills`）就对所有项目生效；只想对某一个仓库生效，放进该仓库根目录下的 `.dsh/skills/` 即可。

验证：下一个模型步骤里，`fresh-eyes-review` 会出现在 skill 目录中。若没有出现，检查目录层级是不是多套了一层——发现只认 `<root>/<name>/SKILL.md`，不认嵌套。

```text
fresh-eyes-review/                 ← 仓库根
├── README.md
├── LICENSE
└── fresh-eyes-review/             ← 要复制的就是这个目录
    ├── SKILL.md
    ├── scripts/
    │   ├── check_review_report.py
    │   └── test_check_review_report.py
    └── references/
        ├── reviewer-prompt.md
        └── anti-patterns.md
```

**不装 DSH 也能用。** 这套方法本身与 DSH 无关：`SKILL.md` 写的是流程，`references/reviewer-prompt.md` 是可直接复制粘贴的提示词模板，门禁脚本是普通 Python（仅标准库）。用别的 agent 时，把"委派一个干净上下文的审查者"换成你那边的等价机制即可——见第 6 节的一个术语陷阱。

---

## 4. 怎么用

### 触发

三种说法任选：

1. **自然语言**：`审一下` / `帮我 review 一下这次改动` / `找找 bug`。skill 的 description 里写了这些触发词，会自动加载。
2. **显式**：`/fresh-eyes-review`。
3. **带范围**：`审一下 frame_builder.py 里这次新增的两帧`。范围越具体，回来的证据越有用。

### 流程

1. **收集材料**——改动范围（`git diff --stat` / 文件清单 / commit 范围）、工作目录绝对路径、验收标准、能跑什么命令、**证据文件写到哪**（如 `.review-evidence/`）、临时产物写到哪。**不要**写"我为什么这么写"，那会把作者的假设传染给审查者。
2. **委派**——用 `subagent`（provider `spawn`）。**不要用 `subagent_fork`**：它以父级已完成轮次作初始内容，会把作者的上下文送过去。提示词用 `references/reviewer-prompt.md`，填满再发。
3. **过门禁**——把报告存成文件，跑：

```bash
# 默认档：校验「位置 / 复现 / 证据 / 反向前置」是否带齐，证据文件在不在、
#         首行是不是 [exit code: N]，反向前置证据的退出码是不是非零，位置真不真
python fresh-eyes-review/scripts/check_review_report.py report.md

# 前置档（动手改之前跑）：重跑「反向前置」命令，要求它现在仍然失败
python fresh-eyes-review/scripts/check_review_report.py --pre-fix report.md

# 重放档（改完之后跑）：重跑复现命令，与落盘证据归一化后逐行 diff
python fresh-eyes-review/scripts/check_review_report.py --replay report.md

# 可选参数：--workdir DIR（默认报告所在目录）、--timeout SEC（默认 120）、
#          --strict（提醒也计为不合格：缺严重度 / 位置不存在 / 缺反向前置 …）
# --pre-fix 与 --replay 互斥：一个验「改之前必须失败」，一个验「改之后能重现」
```

**退出码**

| 码 | 含义 | 你该做什么 |
|---|---|---|
| `0` | 每条发现都带齐证据（`--pre-fix` 下前置命令仍然失败；`--replay` 下全部重放一致且前置已转绿） | **仍然要逐条照抄核实**——格式达标不等于内容为真 |
| `1` | 有条目缺证据；**或反向前置证据记成 exit 0**（命令通过了＝缺陷不成立）；或前置/重放未按要求表现 / 被拒绝表拦下；或交接文档缺必需小节 / 取舍条目为空；或对抗性复审报告缺段、段内没有点名任何一条发现。**（交接文档的取舍缺出处默认只提醒，`--strict` 下才计不合格）** | 缺证据的退回或丢弃，**不要凭它改代码**；前置记成 0 的直接退回；不一致的**升级给人判断**（见第 5 节） |
| `2` | 报告读不了（缺文件、未知参数、编码解不开），或 `--pre-fix` 与 `--replay` 同时给出，或 `--falsify` 没配 `--handoff` / 与 `--pre-fix`、`--replay` 同给 | 这是读取错误，不是"报告不合格"，两件事不能混 |

4. **分流 + 收口**——缺证据的条目重开一个空上下文审查者补证据（前台起的子 agent 结束后没有可寻址的 id，叫不回同一个）；每条修完补一个断言，**把 bug 装回去，测试必须变红**。红不了就继续改断言，不是继续改代码。

### 第二轮回审（可选，价值最高的一轮）

> **默认只跑首轮。** 这一轮要多花一个子代理的时间，决定权在人：执行者不得自行升级。
> 门禁会拦这件事 —— 交接文档必须声明审查模式，声明「首轮」却跑 `--falsify` 直接退 2。

首轮问的是「这段改动有什么问题」。第二轮问的是完全不同的问题：**「上一轮那份报告，哪一条是错的？」**

理由是很实际的失败代价：一次自信的**错误**发现，下游代价最大 —— 它会让人去改本来没错的代码。而首轮的审查者不会知道自己报错了，只有第二个审查者能把它按下去。

两件事支撑这一轮：

- **`references/handoff-template.md`** —— 交接文档（`<工作目录>/.review-handoff.md`）。审查者是空上下文的，它不知道哪些是**已经定死的取舍**，会把它们当缺陷报上来、还认真复现一遍。这份文档把那些取舍写清楚，**同时**给出上一轮已驳回的发现及其理由。
  它也是这套流程里最危险的一份文件，因为**写它的人正是被审的人**。所以每条取舍必须带出处（`HumanDecision` / `RecordedDecision` / `OrchestratorClaim`），且必须写成「影响边界 + 请只报哪类」而不是「别管」—— 否则它就是一份封口文件，而这套门禁唯一的资产就是信誉。门禁会逐条检查出处。
- **`references/adversarial-reviewer-prompt.md`** —— 第二轮的提示词。它要求审查者**动手重跑上一轮的命令**，然后逐条判决：确认成立 / 驳倒 / 未决，三段缺一不可。

```bash
python fresh-eyes-review/scripts/check_review_report.py --falsify --handoff .review-handoff.md round2.md
```

第二轮报告**不走**发现块那套格式 —— 它判的是**报告**，不是代码，不该被逼着为每条都造一个新证据。但它必须说清每条旧发现的去向。

**什么时候值得开这一轮**：改动碰数据 / 凭据 / 权限 / 不可逆操作，或者夜里无人值守跑。写个 UI 文案不必。**换一个模型更好** —— 同族模型会共享盲区（Knight & Leveson 1986），而这一轮最怕的正是「两个审查者一起错」。

### 报告格式（契约）

门禁、提示词模板、这个 README 描述的是同一份格式。改格式要三处一起改，并跑回归。

```markdown
### F1 <一句话结论> · 严重度：高|中|低
- 位置：path/to/file.ext:123
- 复现：python tools/check.py --case power-on
- 证据文件：.review-evidence/F1.txt
- 反向前置：python -m pytest tests/test_power_on.py::test_rejects_disabled_user
- 反向前置证据：.review-evidence/F1-red.txt
- 实测：<一句话摘要；以证据文件为准>
- 影响：<丢数据 / 泄凭据 / 静默失效 / 只是难看>
- 建议修法：<一句话；不确定就写「不确定」>
```

证据文件的内容是硬性的——**首行必须是退出码**，其后是命令的原始输出，不改写、不节选：

```text
[exit code: 0]
checked=1 same=0 attached=0 calls=0
```

`实测` 与 `证据文件` 至少要有一个；有证据文件时以文件为准，`--replay` 档要求必须有证据文件。

**`反向前置` 是这条发现最硬的部分**：一条在**有缺陷的代码上会失败**的命令，它的证据文件首行退出码必须是**非零**。记成 `[exit code: 0]` 意味着命令通过了 = 缺陷不成立，门禁**直接判不合格**（不是提醒）。这一行也不接受「未能执行」——别的字段可以写"跑不了 + 原因"，这一行不行。最理想的是它**在修复后变成通过**：先红后绿，同时证明缺陷存在、且修复真的修掉了它。

两条命令对应两个时刻，别搞混：**`--pre-fix` 在动手改之前跑**（重跑反向前置命令，要求它仍然失败 —— 跑绿了就说明缺陷复现不了，先别修）；**`--replay` 在改完之后跑**（重跑复现命令，与落盘证据比对）。同一个报告先过前者、修完再过后者，这条发现才算走完。

门禁接受几种等价写法：`- 位置：…`、`- **位置**：…`、`location: …`；值可以写在标签同一行，也可以写在下面几行（多行命令、围栏里的真实输出都算）。`反向前置` 的等价标签还包括 `前置复现`、`pre-fix`、`red`。

### 更省的一档

不开审查者也行：只保留收口那一步——每处改动配一个能变红的断言，外加问自己一句「**我怎么知道它真的在跑？**」。有实证支持这一档：抬高上限的是可执行的判据，第二个模型主要是帮你找到"该加哪条判据"。

---

## 5. 诚实的局限

这一节请务必读完再决定要不要用。

**`--replay` 不是沙箱。** 它会执行报告里的命令。有一层拒绝表用来防手滑（覆盖 `rm -rf`、`mkfs`、`dd if=`、`git push` / `reset --hard` / `clean -fd`、`sudo`、`DROP TABLE`、`npm publish`、`dsh plugin` 之类），另有超时（默认 120 秒，可调），但它**挡不住有意绕过**。只在你信任的报告上开这个档；不确定时用默认档，人工核实。

**非确定性输出需要处理。** 时间戳、耗时、临时路径、随机 ID、并发顺序都会让"同一条命令"产生不同输出。正确做法是：审查者在命令里自己设法稳定输出（固定种子、去掉时间字段、只取关键行），或者由门禁做归一化。**当重放不一致时，应当升级给人判断，不要直接当成造假。** 这是设计意图，不是把责任推给使用者——判断"这是造假还是环境差异"目前只有人能可靠地做。

**多一个 LLM 审查者不会自动提高高危缺陷的捕获率。** Tufano 等人的对照实验（29 名专家 / 50+ 小时，arXiv:2411.11401）显示：评审者认为 LLM 报的问题大多有效，但会产生**锚定效应**（只盯 LLM 指出的位置），结果是低严重度发现变多，**高严重度发现并没有增加**，而且没省时间、也没提升信心。

> 这条对本项目同样适用，也是这个 README 里最该被记住的一句：**本项目真正的价值不在"多了一个 AI"，而在"能跑命令 + 强制证据 + 反向验证"这三条纪律。** 如果你只取前半句，收益会远低于预期。

**隔离 ≠ 错误不相关。** Knight & Leveson (1986) 用实验证明：让不同团队**独立开发**同一份需求，故障仍然是相关的——大家会在同一处难的地方犯同一类错（DOI:10.1109/TSE.1986.6312924）。所以想真正提高独立性，要动的是**来源**（不同的模型族、不同的提示词框架、不同的上下文），而不是简单地增加数量。同一底座模型的两个实例仍然共享训练偏差。

**其他已知边界：**

- 门禁检查的是**格式与（重放档下的）一致性**，它无法判断"这条发现重不重要"。
- 缺严重度、位置没行号这类只算提醒，默认不影响退出码；需要更严可以用 `--strict` 把提醒计为不合格。
- 本项目**没有**编排器、角色流水线或平台能力。它是一条纪律，不是一套系统；需要平台的话见第 2 节里那些项目。

---

## 6. 与 DSH 之外生态的关系

这是 **DSH 原生**的 skill：它用 `subagent` 做委派，用 DSH 的 skill 目录机制分发。但方法本身与 DSH 无关，移植到别的 agent 时只需要替换"怎么起一个干净上下文的审查者"这一步。

**一个必须知道的术语陷阱：`fork` 在两个生态里含义正好相反。**

| 生态 | 写法 | 含义 |
|---|---|---|
| Claude Code | `context: fork` | **派生一个隔离上下文**——正是本项目想要的独立性 |
| DSH | `subagent_fork` | **继承父级已完成对话**——审查场景绝对不能用 |

所以本项目的 `SKILL.md` 里那句"别用 fork"在 DSH 语境下是对的，但**直接搬到 Claude Code 语境会被理解成反的**。移植时请把这句话改写成"别用会继承作者会话的那个后端"。

---

## 7. 参考

学术文献：

- Tsui, *Self-Correction Bench*（COLM 2026）——同一错误以"外部"与"自己"两种身份注入，14 个模型呈现 64.5% 自我纠错盲区：https://arxiv.org/abs/2507.02778
- Tufano et al.，29 名专家 / 50+ 小时对照实验——LLM 评审的锚定效应、高危发现未增加：https://arxiv.org/abs/2411.11401
- Knight & Leveson (1986), *An Experimental Evaluation of the Assumption of Independence in Multiversion Programming*, IEEE TSE：https://doi.org/10.1109/TSE.1986.6312924

相关开源项目（均为各自作者所有，本仓库不隶属、不背书，仅作事实引用）：

- momomuchu/make-no-mistakes — `context: fork` + 禁写工具的结构性独立；`mutate.py` 单点变异与 kill-rate 门禁；10 级门禁阶梯：https://github.com/momomuchu/make-no-mistakes
- QwenLM/qwen-code — autofix skill：reproduce-before-fix、mutation probe、提交前门禁（PR #9578）：https://github.com/QwenLM/qwen-code
- andrewstellman/quality-playbook — `BUG-NNN.red.log` / `.green.log` 强制落盘；"落盘 + 重跑 + diff"的防伪造机制：https://github.com/andrewstellman/quality-playbook
- Kappaemme-git/codex-bug-reproducer — "Never claim a bug from code inspection alone"；输出落盘 JSON + 修复前后比对 + 八态证据标签：https://github.com/Kappaemme-git/codex-bug-reproducer
- PerryLink/dsh-doublecheck — DSH 四阶段交付门禁，退出码 0/1/2，red/green 证据门：https://github.com/PerryLink/dsh-doublecheck
- joekytc/dsh-swarm — `validateReviewEvidence`；其 Known limitations 明写 "Review evidence is existence-checked, not replay-proven"：https://github.com/joekytc/dsh-swarm
- anthropics/claude-code — 官方 `code-review`：独立 agent 结构 + 置信度阈值过滤：https://github.com/anthropics/claude-code

> 引用这些项目的目的是**说明本项目站在哪里**，而不是评价它们的质量。第 2.1 节里每一个在对应维度上都至少与本项目持平，多数做得更深。

---

## 8. License

MIT。见 [LICENSE](LICENSE)。

```text
Copyright (c) 2026 Dely0
```

> 发布前请把 `Dely0` 替换成实际署名。

---

## 9. 贡献

欢迎 PR，尤其是**反驳**这个 README 里任何一句话的 PR。

- **改门禁必须跑回归，且必须全绿**：

  ```bash
  python fresh-eyes-review/scripts/test_check_review_report.py
  ```

  这套 **70 条**断言自造夹具、不依赖外部文件，覆盖了这条流水线上真实踩过的坑（末条发现被尾部小节补齐、散文报告靠"无问题"子串蒙混、GBK/UTF-16 误杀、加粗标签被误判、多行证据被判为空、填充词当证据、悬空证据文件、缺少退出码首行、位置指向不存在的文件、位置行号超出范围、含空格路径、非代码后缀写在前面导致的整体绕过、URL 不被当成文件、反向前置证据记成 exit 0、缺反向前置、`--pre-fix` 下缺陷复现不了、`--pre-fix` 与 `--replay` 互斥、`--replay` 下前置命令必须已转绿、交接文档缺出处、对抗性复审缺三段、重放不一致 / 退出码不一致 / 命中拒绝表 / 超时、易变内容归一化……）。

- **加新规则，先加一条会红的断言。** 修之前必须红，修之后必须绿——否则你不知道这条断言是否真的咬住了问题。
- **报告格式是契约。** 改它要同时改 `SKILL.md`、`references/reviewer-prompt.md` 和门禁，并跑回归。
- **不要引入运行时依赖。** 门禁只用 Python 标准库，且刻意停留在 Python 3.8 兼容语法上——这样它在别人机器上的旧解释器里也能跑。
- **如果你发现第 2 节里"没有被做过"的判断是错的**，请优先提 issue 而不是 PR：我会先改那段描述。
