# 独立审查报告（第 3 轮 · 首轮全量审）

- 审查对象：`C:\Users\dupenglai\.dsh\tmp\fer-repo` 未提交工作区改动，基线 `593532b25d1b14cd85b73e7a4c65a27e23a76cbf`
- 交接文档：`.review-handoff.md`（其「已定取舍」的条目只当声明核）
- 环境：Windows / Python 3.11.3 / 无第三方依赖；所有 python 调用都带 `PYTHONDONTWRITEBYTECODE=1`
- 证据目录：`.review-evidence-r3/`
- 说明：本报告里 `F<n>` 是**本报告**的发现编号，与 `check_review_report.py` 源码里注释提到的既有编号（F1/F2/…）无关。
- 每个发现有两份证据：`F<n>-probe.txt` 是**反向前置命令本身**的原始输出（首行退出码非零），`F<n>-reverse.txt` 是同一命令经 `run_evidence.ps1` 落盘时的原始输出；两者内容一致，`*-reverse.txt` 可直接作为「反向前置证据」格式的样例。
- 探针脚本源码已随证据归档到 `.review-evidence-r3/probes/`，可用报告里的命令原样重跑（脚本里的工作目录都是固定路径 `C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3`，只有各自的夹具落在新建临时目录里）。

---

### F1 交接文档的「必需小节」判定是 OR 不是 AND：缺 `## 范围` 的交接文档在 `--strict` 下照样通过 · 严重度：高

- 位置：`fresh-eyes-review/scripts/check_review_report.py`:277-285（`check_handoff` 的 `has_section` 循环）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f1_probe.py C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts\check_review_report.py`
- 证据文件：`.review-evidence-r3/F1-probe.txt`
- 反向前置：同上（探针在缺陷存在时打印 `F1_STILL_ACCEPTED` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F1-reverse.txt`（首行 `[exit code: 1]`）
- 实测：探针造一份只有 `## 已定取舍`、**完全没有 `## 范围`** 的交接文档，跑 `--strict --handoff .review-handoff.md report.md`，门禁输出「格式达标」、`gate exit=0`。代码是 `if any(section in heading for section in HANDOFF_REQUIRED_SECTIONS): has_section = True; break` —— 命中任一小节即认定「必需小节都在」，且 `break` 后不再检查第二个。
- 影响：静默失效。`--handoff` 号称校验「范围为谁」，实际上只有一条取舍条目的文档就能通过，审查者拿到的简报可以完全没有范围/验收标准。这是验收标准 3/4 的判定被削弱，不是显示问题。
- 建议修法：把 OR 改成对两个小节各自判定（`HANDOFF_REQUIRED_SECTIONS` 逐个命中），并去掉 `break`；补一条「只有 `## 已定取舍`、没有 `## 范围` 必须退 1」的断言。

### F2 取舍条目的「出处」是裸子串匹配，条目自称「未经 HumanDecision 确认」也被算作有出处 · 严重度：高

- 位置：`fresh-eyes-review/scripts/check_review_report.py`:299（`if not any(marker in stripped for marker in PROVENANCE_MARKERS)`），标记定义在同文件:138
- 复现：`pwsh -NoProfile -File C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f6_probe.ps1 C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts\check_review_report.py`
- 证据文件：`.review-evidence-r3/F6-probe.txt`
- 反向前置：同上（探针在缺陷存在时打印 `F6_NEGATED_PROVENANCE_PASSES` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F6-reverse.txt`（首行 `[exit code: 1]`）
- 实测：取舍条目原文是 `- 不要报归一化产生的假不一致 | 依据：未经 HumanDecision 确认，是本轮执行者自行决定 | 影响边界：无`（探针同时 `Select-String` 打出命中行，确认匹配就是这句否证）。门禁跑 `--strict`，输出「另有 0 条提醒」「格式达标」，`gate exit=0`。也就是说：**明确声明没有真人决策的条目，反而因为它提到了 `HumanDecision` 这个词而被判定为有出处**。
- 影响：静默失效 + 用出处标注粉饰自利结论。这是「已定取舍」整套出处机制的唯一机械检查，而它把「有出处」降级成「提到过这个词」。交接文档自己把这条机制写成「每条取舍必须带出处，门禁会逐条检查出处」。
- 建议修法：改成先解析「依据：」后的值再匹配（值必须以三个标记之一开头），或至少要求标记前紧邻 `依据：`/`基于`；再加一条「依据：非 HumanDecision/… 开头必须退 1」的断言。

### F3 三种出处标记在门禁下完全等价：自称 `OrchestratorClaim` 与自称 `HumanDecision` 的退出码逐字节相同 · 严重度：中

- 位置：`fresh-eyes-review/scripts/check_review_report.py`:138（`PROVENANCE_MARKERS`）、:299（不区分标记种类）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f7_probe.py C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts\check_review_report.py`
- 证据文件：`.review-evidence-r3/F7-probe.txt`
- 反向前置：同上（探针输出 `F7_PROVENANCE_MARKERS_INTERCHANGEABLE` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F7-probe.txt`（首行 `[exit code: 1]`）
- 实测：同一条取舍，只换标记：`OrchestratorClaim` → `gate exit 0`，`HumanDecision` → `gate exit 0`，且都无提醒。门禁既不把 `OrchestratorClaim` 降级，也不要求 `HumanDecision` 提供可核对的出处（哪一个会话、哪次拍板）。
- 影响：静默失效。交接文档把「出处」当诚实性分级（真人定的 / 记录过的 / 只是编排者主张），但门禁对三者一视同仁，于是写文档的人（正是被审的人）拿 `HumanDecision` 是零成本的。**这一条只报标记等价、不报「真人到底有没有拍板」**：后者不可机械核验，见文末「未能验证」。
- 建议修法：不确定。至少可以让 `OrchestratorClaim` 走提醒通道（默认提醒、`--strict` 不合格），让诚实标注不再是纯吃亏。

### F4 回归套件完全钉不住 `--falsify`：三条规则整条删掉，套件仍然「共 70 条断言，变红 0 条」 · 严重度：高

- 位置：`fresh-eyes-review/scripts/test_check_review_report.py`:473-493（falsify 用例簇）；`:481` 的 `["--falsify", "report.md"]` 夹具
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f3_probe.py`
- 证据文件：`.review-evidence-r3/F3-probe.txt`
- 反向前置：同上（探针把 `if falsify and handoff is None:` 改成 `if False and ...` 后跑整套回归，套件仍 `exit 0`，探针打印 `F3_RULE_UNPINNED` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F3-reverse.txt`（首行 `[exit code: 1]`）
- 实测：定向变异套件（`.review-evidence-r3/mutation-harness.raw.txt`）逐条破坏门禁规则，结果：

  | 变异 | 破坏的规则 | 套件结果 |
  |---|---|---|
  | M1 `--falsify` 不再要求 `--handoff` | 验收标准 2 前半 | 70 条全绿（**没咬住**） |
  | M2 删掉「缺三段」检查 | 验收标准 2 后半 | 70 条全绿（**没咬住**） |
  | M3 删掉「每条判定带标注」检查 | 验收标准 3 | 70 条全绿（**没咬住**） |
  | M4 把 `未决` 从必需段里去掉 | 验收标准 3 | 70 条全绿（**没咬住**） |
  | M5 交接文档只需 `范围` 一节 | 验收标准 4 | 70 条全绿（**没咬住**） |
  | M6 删掉取舍出处检查 | 验收标准 3 | 变红 1 条：`handoff_missing_provenance` |
  | M7 删掉空取舍检查 | 验收标准 4 | 变红 1 条：`handoff_no_tradeoffs` |
  | M8 把「反向前置太短」阈值 8 改成 1 | 既有规则 | 70 条全绿（**没咬住**） |

  根因：用例 `falsify_needs_handoff` 的夹具 `{".review-handoff.md": HANDOFF_OK, "report.md": FALSIFY_OK}` 里**没有 `report.md` 这个文件**，而 `main()` 把 `report.md` 追加在命令末尾。门禁在读报告时就 `ReadError` 退 2 —— 断言期望 2，于是**无论规则在不在，这条断言都绿**。实际是通过了「报告读不了」这条完全不同的分叉。
- 影响：静默失效。验收标准 5 说的「新增断言能钉住新规则」在这里不成立：`--falsify` 的判定逻辑可以整块删掉而 CI 依旧全绿；M8 说明既有的「反向前置太短」也从没被执行过。
- 建议修法：`falsify_needs_handoff` 的夹具补上 `report.md`（内容用 `FALSIFY_OK`），并断言退出码是 2 **且** stderr 含「必须同时给出 --handoff」；再补「缺任一必需段」的逐段断言与「判定标注」断言。

### F5 对抗性复审可以完全空洞：一句「逐条复核完毕」就能通过 `--strict`，而门禁打印「每条判定都标了出处」 · 严重度：高

- 位置：`fresh-eyes-review/scripts/check_review_report.py`:322-347（`check_falsify_report`）、:959（成功话术）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f4_probe.py C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts\check_review_report.py`
- 证据文件：`.review-evidence-r3/F4-probe.txt`
- 反向前置：同上（探针输出 `F4_FALSIFY_VACUOUS_PASSES` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F4-reverse.txt`（首行 `[exit code: 1]`）
- 实测：第二份报告正文是

  ```
  ## 我确认成立的
  - 逐条复核完毕 · 判定：成立
  ## 我驳倒的
  - 上轮结论有误 · 判定：驳回
  ## 未决
  - 有几条没能本地验证
  ```

  它**没有点名任何一条上一轮发现**，门禁 `--falsify --strict` 输出「对抗性复审通过 —— 分段齐全，每条判定都标了出处。」`gate exit=0`。**这句话里的「每条判定都标了出处」是假的**：报告里没有任何出处，三段内容也不含任何发现编号。另外探针里 `## 我确认成立的 / ## 我驳倒的 / ## 未决` 三个空标题在默认档下也是退 0（`--strict` 才因「没有逐条判定」提醒变红），也就是 `--falsify` 默认档对完全空白的报告判「通过」。
- 影响：静默失效。这一档是整条流水线里专门用来「把上一轮的错误发现按下去」的，而它可以被一份没有判决任何东西的报告满足。对下游来说是「机器验过了」的假信号。
- 建议修法：门禁无法知道上一轮有哪些发现，但可以要求三段各自至少有一条**带发现编号**的条目（例如 `F<n>`），并让 `claims == 0` 成为 problem 而不是 warning；成功话术要改成实际成立的表述。

### F6 `--falsify` 把 `--replay` / `--pre-fix` 静默吞掉：输出与纯 `--falsify` 逐字节相同 · 严重度：中

- 位置：`fresh-eyes-review/scripts/check_review_report.py`:943-960（mode C 分支在发现块循环之前 `return`）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f5b_probe.py C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts\check_review_report.py`
- 证据文件：`.review-evidence-r3/F5-probe.txt`
- 反向前置：同上（探针打印 `F5_FALSIFY_IGNORES_REPLAY: ... 逐字节相同 = True` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F5-reverse.txt`（首行 `[exit code: 1]`）
- 实测：同一份第二轮报告、同一个 `--handoff`，三次运行：
  - `--falsify --strict` → 退 0，输出「对抗性复审通过 —— 分段齐全，每条判定都标了出处。」
  - `--falsify --replay --strict` → 退 0，**逐字节相同**
  - `--falsify --pre-fix --strict` → 退 0，**逐字节相同**

  输出里没有任何一行重放/前置结果。对照：`--pre-fix` 与 `--replay` 互斥是被显式拒绝（退 2）的，而 `--falsify` 与这两者同给却既不报错也不执行。
- 影响：静默失效。`README.md`/`SKILL.md` 都写「`--pre-fix` 不是可选项」，而照这个建议在模式 C 上加 `--pre-fix`/`--replay` 的人会拿到一个退 0、什么都没验的运行结果。对 CI 尤其危险，因为退出码被当成「验过了」。
- 建议修法：在与 `--pre-fix`/`--replay` 互斥的同一处，对 `--falsify` 组合同样退 2 并说明；或让 mode C 分支继续把带证据文件的条目交给 `replay_finding`。

### F7 `--handoff` 缺出处的默认档行为（提醒而非不合格）在 README 的退出码表里被写成「不合格」 · 严重度：低

- 位置：`README.md`:196（退出码 `1` 行）；`fresh-eyes-review/SKILL.md`:204（「必需小节在不在」）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f8_probe.py`
- 证据文件：`.review-evidence-r3/F7-doc-consistency.txt`
- 反向前置：同上（探针语义：断言「缺出处的交接文档在默认档退 0」与 README 表格的「不合格即退 1」矛盾，矛盾成立即 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F7-doc-consistency.txt`（首行 `[exit code: 1]`）
- 实测：README 退出码表 `1` 行写「…或交接文档与对抗性复审报告不合格」，没有任何「默认档只提醒」的限定；同一节上方却写「门禁会逐条检查出处」。实际行为：交接文档取舍缺出处、默认档退 **0**（仅 `[WARN]`），`--strict` 才退 1（另见 `.review-evidence-r3/probe2-default-vs-strict.txt` 里 `p2_handoff_default` 与 `p6_double_count` 两例）。另外 `SKILL.md`:204 写「同时校验交接文档——必需小节在不在」，而实际只要命中「范围」「已定取舍」其一（见 F1）。`SKILL.md` 里「缺出处默认只提醒」这句本身是**属实**的（实测退 0），所以这一条只报 README 与 `SKILL.md`:204 两处。
- 影响：只是文档不一致，但会让按 README 接 CI 的人误判「缺出处会拦」；SKILL.md 的「必需小节」表述与 F1 的实现缺陷叠加，等于给缺陷做了背书。
- 建议修法：README 退出码 `1` 行补「（交接文档缺出处默认只提醒，`--strict` 下才计不合格）」；`SKILL.md` 改为「校验两个必需小节是否都在」。

### F8 交接文档的验收标准 5 与实际不符：仓库里从来没有「53 条断言」 · 严重度：中

- 位置：`.review-handoff.md`:16（「改动前的 53 条断言全部保持通过，新增后合计 70 条全绿」）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f9_probe.py`
- 证据文件：`.review-evidence-r3/F9-assertion-count.txt`
- 反向前置：同上（探针断言「改动前自报 53」，实际 36，断言失败即 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F9-assertion-count.txt`（首行 `[exit code: 1]`）
- 实测：把 `HEAD` 版门禁与套件导出到系统临时目录直接跑，套件自报「**共 36 条断言**，变红 0 条」；工作区版自报「共 70 条断言」。工作区测试文件里的用例元组 34 条 + 2 条手写用例 = 36，与 HEAD 版自报数完全一致。`git log` 显示该测试文件在基线提交 `593532b` 才首次出现，之后再无提交。所以「改动前的 53 条」在这个仓库里对不上任何东西：53 + 新增 17 = 70 的算式，把基线的 36 误当成 53。
- 影响：不是代码缺陷，是**验收标准本身不可核对**。审查者被要求「以交接文档的范围一节为准，逐条核实」，而其中一条的基准数是错的。交接文档正是要给审查者可信情报的那份文件。
- 建议修法：把该行改成「改动前 36 条断言全部通过，新增后合计 70 条全绿」，或写明 53 这个数的出处。

### F9 证据文件路径后面多一句括注就被判「证据文件不可用」：inline code 与注解并存时误杀合法报告 · 严重度：中

- 位置：`fresh-eyes-review/scripts/check_review_report.py`:546-551（`strip_ticks`）、:712-713（`check_evidence_file` 用清洗后的值直接当路径）
- 复现：`python C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3\f10_probe.py C:\Users\dupenglai\.dsh\tmp\fer-repo\fresh-eyes-review\scripts\check_review_report.py`
- 证据文件：`.review-evidence-r3/F10-probe.txt`
- 反向前置：同上（探针造两份只差一个括注的报告：裸写法必须退 0、带括注必须退 1，否则打印 `F10_ANNOTATED_POINTER_MISJUDGED` 并 `exit 1`）
- 反向前置证据：`.review-evidence-r3/F10-probe.txt`（首行 `[exit code: 1]`）
- 实测：两份报告的其余字段完全一致（位置 / 复现 / 反向前置 / 反向前置证据 / 实测，均在 workdir 下有真实文件）：
  - `- 证据文件：\`ev/F1.txt\`` → 退 0，「共 1 条发现：1 条合格」
  - `- 证据文件：\`ev/F1.txt\`（原始输出，未摘录）` → 退 **1**，`- 证据文件不可用：证据文件读不了：[Errno 2] ...'\`ev/F1.txt\`（原始输出，未摘录）'`

  `strip_ticks` 只在「反引号是整串值的首尾字符」时才剥掉反引号，所以只要路径后面跟了任何注解，整串（含反引号与中文括注）就被当成文件名。`README.md`:233 与 `SKILL.md` 都宣称门禁接受「几种等价写法」并推荐把值写成 inline code，但没有任何一处写「路径必须是这一行的全部内容」。
- 影响：**误报**——合法输入被判不合格（退 1），而且提示信息把锅指向「证据文件读不了」，会让人去查文件而不是查写法。
- 建议修法：从值里提取第一个「看起来像路径」的 token（例如取反引号内内容，或取 `路径:行号` 正则的首个匹配）再拼 workdir；或在模板里明确禁止在路径后写注释。

---

## 未能验证

1. **三种出处标记背后「真人确实做过相应决定吗」不可机械核验。** 交接文档把第一条标 `HumanDecision`、第二条标 `RecordedDecision`（「见本轮会话上下文」），我无法从仓库里找到任何记录这些决定的文件：`git status` 只有这 8 个文件加 `.review-handoff.md` 本身，`git log` 只有一个基线提交，交接文档也没有引用会话/工单编号。我试过的：`git log --oneline`、`grep` 仓库内的 `HumanDecision`/`RecordedDecision` 字面量（只出现在门禁、模板、测试夹具与这份交接文档里）、检查是否存在会话记录文件。**结论只到这里：这两条标注在仓库内无出处可核对**；是不是「用出处标注粉饰自利结论」我拿不出机械证据，所以没有按发现计数。F3（标记等价）是同一问题的机械可证部分。
2. **`--falsify` 段的字符串匹配边界只做了部分验证。** 我确认了小节识别是 `section in heading` 的子串匹配（例如「## 我确认成立的说法」也命中「我确认成立的」），但我没有构造出「只用子串绕过必需段」的可执行反例，因为要同时满足 `claims > 0` 才能避开「没有逐条判定」提醒——写成 F5 那种空泛条目时它其实是通过的。我判断这条与 F5 是同一个洞的两个面，故并入 F5，未单列。
3. **归一化「十类」的说法核对结果是成立的**，不是问题：导入门禁后 `len(NORMALIZERS) == 10`（证据 `.review-evidence-r3/F9-normalizer-count.txt`，退出码 0）。列在这里是为了说明这条我查过而否掉了。
4. **`falsify_unmarked_claim` 这条断言是否真的咬住 M3。** 定向变异显示 M3（删掉判定标注检查）下套件仍全绿；我另外单独跑了该用例的夹具（`{".review-handoff.md": HANDOFF_OK, "report.md": <只有「我确认成立的」一节>}`），它退 1 的原因是「缺少小节」而不是标注缺失。我没有逐条拆开验证它是否在与 M3 无关的路径上通过，故只在 F4 的表格里陈述套件结果，不额外下结论。
5. **本报告自身的可重放性。** 我按 F9 的写法把「证据文件」写成裸路径（不加反引号、不跟注解），所以把本报告喂回门禁时只有 F1 一条因 F9 那个缺陷被判不合格；其余各条的字段都已按模板写全。这只是我在自查，不作为发现。
