# Skill Script Execution v0.1.0 设计文档

## 1. 文档信息

| 项目   | 内容 |
| ------ | ---- |
| 模块   | Skill Capability / Script Execution |
| 所属项目 | echo-agent |
| 版本   | v0.1.0 |
| 状态   | Design |
| 依赖文档 | [skill v0.1.0 设计文档](./skill%20v0.1.0%20设计文档.md) |
| 设计方向 | Sandbox as tool；执行后端仅 **local** 与 **docker** |

---

## 2. 背景与问题

### 2.1 现状

Skill 能力已支持：

- `SKILL.md` 解析与 Progressive Disclosure；
- `load_skill`：加载指令正文；
- `read_skill_resource`：按需读取 `scripts/` / `references/` / `assets/` / `additional_resources` 等文本资源；
- `SkillPackage.scripts` 等字段枚举附属文件。

当前 **没有** 在 runtime 中执行 Skill 包内脚本的能力。

### 2.2 问题

一类 Skill（如 `skill-creator`、`xlsx`）在 `SKILL.md` 中要求 Agent 执行包内脚本，例如：

```text
python -m scripts.package_skill <path>
python scripts/recalc.py output.xlsx
```

在现有实现下，模型最多通过 `read_skill_resource` 阅读源码，无法真正执行，导致此类 Skill 无法闭环。

### 2.3 设计边界澄清

| 事实 | 结论 |
| ---- | ---- |
| 缺的是「执行面」（Tool） | 先补 `run_script` Tool |
| 缺成品 OS 沙箱 | 沙箱是 Runner 后端，不是 Tool 前置条件 |
| 云端沙盒不适用本项目 | **不做** E2B / LangSmith Sandbox 等云端方案 |
| bubblewrap（Codex Linux 路径） | **本期不做**；仅 Linux、且与 Windows 开发机不兼容 |

执行后端本期只保留：

1. **local**：本机进程；
2. **docker**：本机 Docker 容器隔离。

---

## 3. 设计目标

### 3.1 功能目标

1. 提供内置 Tool **`run_script`**，供模型在 Skill 指导下按需执行包内脚本；
2. 支持可插拔 Runner：`local` | `docker`；
3. 默认关闭执行能力（安全默认）；打开后仍受路径 / 解释器 / 超时等硬约束；
4. 可选 HITL 审批后再执行；
5. 与现有 `load_skill` / `read_skill_resource` / ReAct / ToolRegistry 无缝集成。

### 3.2 架构目标

1. **Skill 只指导，Tool 才执行**（延续 skill v0.1.0 职责划分）；
2. 不修改 ReAct 核心图结构；不引入独立 Skill Agent / Skill Graph Node；
3. 采用 LangChain / Deep Agents 推荐的 **Sandbox as tool** 模式：Agent 在宿主，执行经 Tool 进入 Runner；
4. Tool 契约稳定，Runner 可替换；
5. **`SkillScriptConfig` 不进入 `AgentConfig`**：`AgentConfig.skill_list` 只声明可用 Skill 边界与定位；脚本执行策略为独立配置，在组装 Tool / Runner 时注入。

### 3.3 非目标（v0.1.0）

- 云端沙盒（E2B、LangSmith Sandbox、Modal 等）；
- bubblewrap / Codex `CodexSandboxExecutionPolicy`；
- 开放式任意 shell（`bash -c "..."` 作为第一公民）；
- Agent 整体跑进沙盒（Agent-in-sandbox）；
- HTTP Skill 的脚本执行；
- skill-creator 级子代理 / eval 编排全流程；
- Deep Agents `backend` 整套文件系统工具（`ls` / `write_file` / 通用 `execute`）。

---

## 4. 总体架构

```text
LLM / Skill 指令
        │
        ▼
   run_script (@tool)
        │
        ├─ 校验：LOADED / path / allowed_roots / timeout ...
        │
        ▼
 SkillScriptRunner（协议）
        ├─ LocalProcessRunner     ← runner=local
        └─ DockerRunner           ← runner=docker
        │
        ▼
   ScriptResult → Tool Observation
```

与现有 Skill 工具并列：

```text
load_skill              → 激活指令（Level 2）
read_skill_resource     → 读资源（Level 3 读）
run_script              → 执行脚本（Level 3 执行）
```

---

## 5. Tool 契约：`run_script`

### 5.1 命名

工具名定为 **`run_script`**（不再使用 `run_skill_script`）。

语义：在已声明的 Skill 包上下文中，按白名单执行脚本；不是通用本机 shell。

### 5.2 参数

| 参数 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| `name` | `str` | 是 | Skill 名称（`AgentConfig.skill_list` 中的 key / frontmatter.name 约定与现网一致） |
| `path` | `str` | 是 | 相对 Skill 根的脚本路径，如 `scripts/package_skill.py` |
| `args` | `list[str]` | 否 | 传给脚本的参数列表；默认 `[]` |
| `cwd` | `str \| None` | 否 | 工作目录：相对 `workspace_root`（若配置）或相对 Skill 根；默认 Skill 根 |
| `timeout_sec` | `int \| None` | 否 | 覆盖配置默认超时 |

### 5.3 返回

返回给模型的字符串（或等价结构化再序列化），建议固定字段：

```text
exit_code: <int>
stdout:
<truncated stdout>
stderr:
<truncated stderr>
```

约束：

- `stdout` / `stderr` 分别截断到配置上限（见 §7）；
- 截断时附加明确标记（如 `[truncated]`）；
- 校验失败、未启用、Runner 不可用等：返回可读错误字符串，不抛未捕获异常到 Strategy（与现有 skill 工具一致）。

### 5.4 Tool Description（对模型）

要点：

- 仅在 Skill 指令要求执行包内脚本时使用；
- 必须先 `load_skill`；
- `path` 为 Skill 包内相对路径，通常位于 `scripts/`；
- 不要臆造宿主机任意命令；需要读文件时用 `read_skill_resource`。

---

## 6. 配置设计

### 6.1 归属原则（不进入 AgentConfig）

| 配置 | 归属 | 职责 |
| ---- | ---- | ---- |
| `AgentConfig.skill_list` | `AgentConfig` | 声明有哪些 Skill、路径/URL（能力边界） |
| `SkillScriptConfig` | Skill 能力模块（独立模型） | 是否允许执行、Runner、白名单、超时等（执行策略） |

**明确约束：**

1. **`SkillScriptConfig` 不作为 `AgentConfig` 字段**，也不并入 Adapter `AgentConfig` proto；
2. 不写入 `RuntimeConfig`（Runtime 只管 checkpointer / store，与脚本沙箱无关）；
3. 配置落在 `capability/skill`（建议 `script/config.py`），由宿主在 **组装 Agent / 注册 toolkit** 时显式传入。

理由：与 skill v0.1.0「AgentConfig 只声明 Skill 边界与定位，不内嵌执行逻辑」一致；跨语言 Adapter 的 `AgentConfig` 也不必为脚本沙箱膨胀。

### 6.2 注入方式

推荐（二选一，实现期择一即可）：

```text
方式 A（推荐）：
  Agent(..., skill_script_config: SkillScriptConfig | None = None)
  └─ _register_builtin_toolkit 时若 config.enabled 则注册 run_script

方式 B：
  宿主自行 create_run_script_tool(manager, config) 后并入 tool_list
  └─ Agent 不感知 SkillScriptConfig
```

- 未传入或 `enabled=false`：**不注册** `run_script`；
- 默认值等价于「功能关闭」，无需改现有 `AgentConfig` 构造代码。

### 6.3 模型示意

```python
# echo_agent/core/capability/skill/script/config.py（建议路径）

class SkillScriptDockerConfig(BaseModel):
    image: str = "python:3.12-slim"
    network: Literal["none", "bridge"] = "none"
    memory: str | None = None       # 如 "512m"
    cpus: float | None = None
    # 预留：额外只读挂载、env 白名单等

class SkillScriptConfig(BaseModel):
    enabled: bool = False
    runner: Literal["local", "docker"] = "local"
    timeout_sec: int = 60
    max_stdout_bytes: int = 64 * 1024
    max_stderr_bytes: int = 64 * 1024
    allowed_roots: list[str] = Field(default_factory=lambda: ["scripts"])
    require_hitl: bool = False
    workspace_root: str | None = None
    python_executable: str = "python"
    docker: SkillScriptDockerConfig = Field(default_factory=SkillScriptDockerConfig)
```

### 6.4 字段说明

| 字段 | 说明 |
| ---- | ---- |
| `enabled` | 总开关；默认 `false`，未开启时不注册 `run_script` |
| `runner` | `local` 或 `docker` |
| `timeout_sec` | 默认超时 |
| `max_stdout_bytes` / `max_stderr_bytes` | 输出截断 |
| `allowed_roots` | 允许执行的路径前缀（相对 Skill 根）；默认仅 `scripts` |
| `require_hitl` | 为 true 时，执行前走现有 Approval 流程 |
| `workspace_root` | 可选可写工作区；Skill 根默认可只读语义（docker 挂载强制 RO） |
| `python_executable` | local 使用的解释器；docker 内通常为镜像内 `python` |
| `docker.*` | 仅 `runner=docker` 时生效 |

### 6.5 扩展 `allowed_roots` 的约定

- 默认：`["scripts"]`。
- 若需执行 `eval-viewer/generate_review.py` 一类路径，由宿主在 **`SkillScriptConfig`** 中显式追加 `"eval-viewer"`，**不**默认放开全部 `additional_resources`。
- `references/`、`assets/` 默认不可执行。

---

## 7. 安全硬约束（两 Runner 共用）

在调用 Runner 之前统一校验；任一失败则不启动进程/容器。

1. **功能开关**：已注入的 `SkillScriptConfig.enabled == true`（通常未启用则工具未注册，此检查为防御性）。
2. **Skill 类型**：仅 `SkillType.FILE`；HTTP Skill 返回不支持。
3. **生命周期**：目标 Skill 须已在当前 Runtime Context 中为 `LOADED`；成功后 `touch_skill`。
4. **路径**：
   - 规范化分隔符；拒绝空路径、绝对路径、`..` 逃逸；
   - `resolve()` 后必须位于 Skill 根之下；
   - 相对路径的第一段（或配置的前缀匹配）必须落在 `allowed_roots`；
   - 目标必须是已存在的文件。
5. **解释器**：v0.1.0 仅支持以配置的 Python 解释器执行 `.py` 脚本（或 `python -m` 形式若后续扩展，须另开条款）；禁止 `shell=True` / 字符串拼命令。
6. **参数**：`args` 元素必须为字符串；不做 shell 展开。
7. **超时**：必有上限；超时杀进程/停容器，并在结果中标明。
8. **输出**：stdout/stderr 按字节或字符截断，防止撑爆模型上下文。
9. **cwd**：解析后不得逃出 `workspace_root`（若配置）与 Skill 根所允许的联合边界；具体规则实现时写清并单测。

> 说明：以上为**契约级约束**。`local` 不提供 OS 级隔离；`docker` 提供容器级隔离。二者都不能单独防御 prompt injection 导致的「沙盒/宿主权限内作恶」——生产环境建议 `require_hitl=true`，并谨慎打开 `enabled`。

---

## 8. Runner 设计

### 8.1 协议

```python
class ScriptResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    truncated_stdout: bool = False
    truncated_stderr: bool = False
    timed_out: bool = False


class SkillScriptRunner(Protocol):
    async def run(
        self,
        *,
        skill_root: Path,
        script: Path,          # 已校验、位于 skill_root 内
        argv: list[str],       # 不含解释器；或约定含完整 argv
        cwd: Path,
        env: dict[str, str],
        timeout_sec: float,
    ) -> ScriptResult: ...
```

工厂根据 `SkillScriptConfig.runner` 创建 `LocalProcessRunner` 或 `DockerRunner`。

### 8.2 LocalProcessRunner（本机）

**行为：**

- 使用 `asyncio.create_subprocess_exec(python_executable, script, *args, ...)`；
- `cwd` 为校验后的工作目录；
- `env`：最小继承 + 可选 `PYTHONPATH=skill_root`（便于 `python -m scripts.xxx` 类用法若后续支持）；
- 超时后 terminate / kill；
- 收集 stdout/stderr 并截断。

**适用：**

- 本地开发、内网、**信任** Skill；
- 依赖宿主软件的 Skill（如 LibreOffice、本机已装包）；
- Windows 默认路径。

**不适用单独作为生产不可信 Skill 的硬隔离。**

### 8.3 DockerRunner（本机 Docker）

**行为（示意）：**

```text
docker run --rm \
  -v <skill_root>:/skill:ro \
  -v <workspace_root>:/workspace:rw \   # 若配置了 workspace
  --network none \                      # 默认
  --memory ... --cpus ... \             # 若配置
  -w <container_cwd> \
  <image> \
  python /skill/<relative_script> <args...>
```

**约定：**

| 项 | 约定 |
| -- | ---- |
| Skill 挂载 | 只读 `/skill` |
| Workspace | 可写 `/workspace`（未配置则可不挂或挂临时目录） |
| 网络 | 默认 `none`；仅显式配置 `bridge` 时放开 |
| 镜像 | 由配置指定；宿主需保证依赖已在镜像内 |
| Docker 不可用 | 清晰失败（不静默回退 local，除非未来单独配置 `fallback`） |

**适用：**

- 需要硬隔离、固定 Python/依赖版本；
- 纯 Python 脚本（打包、校验等）。

**注意：**

- 依赖 LibreOffice / 宿主 CLI 的 Skill 应使用 `local`，或使用预装完整依赖的自定义镜像；
- Windows 需 Docker Desktop / 兼容引擎；路径挂载需处理 Windows 路径格式。

### 8.4 Runner 选择建议

| 场景 | 推荐 |
| ---- | ---- |
| 开发调试、Windows | `local` |
| 可信 Skill + 宿主依赖 | `local` |
| 不可信或生产隔离、纯脚本 | `docker` |
| 无 Docker 环境 | 仅 `local`，且谨慎 `enabled` |

---

## 9. 与现有模块的集成

### 9.1 Tool 注册

- 位置：与现有 Skill 工具相同，建议 `echo_agent/core/tool/toolkit/skill.py`（或同级 `script.py`）。
- 工厂：`create_run_script_tool(skill_manager, runner, config)`，其中 `config` 为独立的 `SkillScriptConfig`。
- 注册时机：Agent / 宿主组装 toolkit 时；仅当传入的 `SkillScriptConfig.enabled` 为 true 时注册（不读 `AgentConfig`）。
- 执行期：复用 `set_skill_runtime_context` / `get_skill_runtime_context`，与 `load_skill` 一致。
- **禁止**从 `AgentConfig` 解析脚本执行开关或 Runner。

### 9.2 SkillManager

- `build_skill_package` / `has_skill` / `touch_skill` 复用现有 API；
- 不在 Manager 内直接 subprocess；Manager 只提供包元数据与生命周期。

### 9.3 Prompt

更新 `skill_usage_policy.md`：

- 指令引用脚本时，使用 `run_script` 执行；
- 需要阅读脚本或文档时，使用 `read_skill_resource`；
- 不得假设存在通用 shell / bash 工具。

`load_skill` 成功返回中可列出 `scripts`（及配置允许的可执行根下文件），降低路径猜测。

### 9.4 HITL

当 `require_hitl=true`：

- 在真正调用 Runner 前进入现有 Approval 流程；
- 审批描述应包含：`name`、`path`、`args`、`runner`、`timeout_sec`；
- 拒绝则返回未执行说明。

具体挂接方式与现网 Tool 审批模式对齐（实现阶段对照 HITL ApprovalFlow）。

### 9.5 对 ReAct / Graph

- 无新 Node；仍由 ToolNode → ToolExecutor 执行；
- 不改变 checkpoint / session 隔离模型；沙盒实例不跨无关联 session 共享（v0.1.0 docker 为每次 `docker run --rm`，无长驻容器）。

---

## 10. 执行流程

```text
模型决定调用 run_script(name, path, args, ...)
        │
        ▼
enabled? ──否──► 返回「未启用」
        │是
        ▼
取 Runtime Context / SkillPackage
        │
        ▼
LOADED 且 FILE？ ──否──► 返回错误
        │是
        ▼
校验 path ∈ allowed_roots 且未逃逸
        │
        ▼
require_hitl? ──是──► Approval ──拒绝──► 返回未执行
        │否/批准
        ▼
Runner.run(...)
        │
        ▼
touch_skill(name)
        │
        ▼
格式化 ScriptResult → ToolMessage
```

---

## 11. 模块落位（建议）

```text
echo_agent/core/
  agent/
    agent_config.py         # 仅 skill_list；不含 SkillScriptConfig
  tool/toolkit/
    skill.py                # 现有 load / read；新增 create_run_script_tool
  capability/skill/
    script/                 # 新建（名称可调整）
      config.py             # SkillScriptConfig / SkillScriptDockerConfig（独立于 AgentConfig）
      runner.py             # Protocol + ScriptResult
      local_runner.py
      docker_runner.py
      validate.py           # 路径与白名单校验
```

文档与代码命名以最终实现为准；本设计约束的是职责边界，而非强制目录名。

---

## 12. 分阶段落地

| 阶段 | 交付 | 验收 |
| ---- | ---- | ---- |
| **A** | 本文档评审通过；Config / Tool 契约冻结 | 评审签字或等价确认 |
| **B** | `LocalProcessRunner` + `run_script` + 校验；默认 `enabled=false` | 本机执行简单 `scripts/*.py`；路径逃逸单测 |
| **C** | Prompt 更新；`load_skill` 可列脚本；成功 `touch_skill` | ReAct 能按指令调用 `run_script` |
| **D** | `require_hitl` 接入 | 拒绝则不执行 |
| **E** | `DockerRunner` + docker 配置 | 同脚本在 docker 下可跑；无 Docker 时报错清晰 |
| **F** | 测试矩阵：未启用 / 未 load / 超时 / 截断 / local / docker(skip if no daemon) | CI 通过 |

推荐实现顺序：**A → B → C → D → E → F**（先 local，后 docker）。

---

## 13. 与典型 Skill 的预期关系

| Skill 类型 | 预期 |
| ---------- | ---- |
| 纯 Python 脚本（打包、校验、生成报告） | local / docker 均可 |
| 依赖 LibreOffice 等宿主软件（xlsx/pptx） | **local**，或定制重镜像 + docker |
| skill-creator 中调用本机 CLI 的步骤 | 仅 **local**；docker 路径文档标明不支持 |
| 仅 references 文档型 Skill | 无需 `run_script` |

---

## 14. 明确放弃的方案（备忘）

| 方案 | 原因 |
| ---- | ---- |
| 云端沙盒 | 项目约束：不可用 |
| bubblewrap | 仅 Linux/WSL2；Windows 开发机不适用；策略自管成本高；本期聚焦 local+docker |
| 通用 `execute(command: str)` | 攻击面过大；与 Skill 包白名单模型不符 |

若未来 Linux 生产环境需要「无 Docker daemon 的轻量隔离」，可再开专题评估 bubblewrap，不在本版本范围。

---

## 15. 设计原则总结

1. **Sandbox as tool**：执行能力封装为 `run_script`，绑定进现有 Tool 体系。
2. **Skill ≠ 执行器**：Skill 提供指导与资源；Runner 负责副作用。
3. **配置与 AgentConfig 分离**：`skill_list` 在 AgentConfig；`SkillScriptConfig` 独立注入，不进 AgentConfig / RuntimeConfig / proto。
4. **安全默认关闭**：`enabled=false`；打开后仍有路径与超时硬约束。
5. **后端可插拔**：`local` 优先落地，`docker` 提供硬隔离。
6. **不做云端、不做 bwrap（本期）**。
7. **不改 ReAct 主路径**。

---

## 16. 参考

- 仓内：[skill v0.1.0 设计文档](./skill%20v0.1.0%20设计文档.md)
- LangChain Deep Agents：[Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes)（Sandbox as tool 模式）
- LangChain Agents Middleware：`HostExecutionPolicy` / `DockerExecutionPolicy`（本机 vs Docker 策略对照，实现不强制依赖该 middleware）
