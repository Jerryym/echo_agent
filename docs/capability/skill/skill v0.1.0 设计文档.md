# echo-agent Skill 能力设计文档

## 1. 文档信息

| 项目   | 内容                   |
| ---- | -------------------- |
| 模块   | Skill Capability     |
| 所属项目 | echo-agent           |
| 状态   | Design               |
| 目标版本 | TBD                  |
| 设计方向 | 对齐通用 Agent Skills 规范 |

---

## 2. 背景

`echo-agent` 当前已经具备 ReAct Agent 执行模式、Tool 调用体系、MCP Tool 支持、HITL 机制以及基于 LangGraph 的 Runtime。

随着 Agent 能力增强，需要支持一种新的能力扩展方式：让 Agent 可以按需加载某个领域的知识、规则、流程以及辅助资源。

该能力定义为：`Skill`

Skill 与 Tool 的职责不同：

| 类型    | 职责             |
| ----- | -------------- |
| Tool  | 执行动作，产生外部影响    |
| Skill | 提供领域知识、规则和执行指导 |

例如：

Tool：

```text
query_database()
send_email()
create_order()
```

Skill：

```text
pdf processing skill
software development skill
customer support skill
```

---

## 3. 设计目标

### 3.1 功能目标

Skill 能力需要支持：

1. Skill 以目录形式组织；
2. 使用 `SKILL.md` 作为入口文件；
3. 通过配置声明可用 Skill 及其位置；
4. Agent 可以按需加载 Skill；
5. Skill 支持附属资源；
6. 支持 Progressive Disclosure；
7. 支持未来远端 Skill。

### 3.2 架构目标

设计需要满足：

1. 不修改 ReAct 核心执行流程；
2. 不引入独立 Skill Agent；
3. 不引入 Skill Graph Node；
4. 复用现有 Tool 系统；
5. 与 MCP、HITL 保持独立；
6. 本地和远端 Skill 使用统一抽象；
7. AgentConfig 只声明 Skill 边界与定位，不内嵌执行逻辑。

---

## 4. Skill 总体设计

Skill 定义为一个领域能力单元，由一个 Skill Package 表示。

整体关系：

```text
Skill
 |
 v
Skill Package
 |
 v
Resource Tree
```

Skill 不是单个文件，而是一组资源。

例如：

```text
pdf/
├── SKILL.md
├── scripts/
│   └── extract.py
├── references/
│   └── specification.md
└── assets/
    └── template.docx
```

其中：

```text
SKILL.md
```

是 Skill 的入口文件。

---

## 5. Skill Package 设计

### 5.1 定义

Skill Package 表示一个可访问的逻辑资源树。

这里的 Package 不是压缩包，而是表示 Skill 内部资源组织结构。

例如：

```text
Skill Package

├── SKILL.md
├── references/
├── scripts/
└── assets/
```

本地：

```text
Filesystem
    ↓
Skill Package
```

远端：

```text
Remote Resource Tree
    ↓
Skill Package
```

上层逻辑不关心 Skill 的实际存储位置。

### 5.2 SkillPackage 抽象

定义：

```python
class SkillPackage(Protocol):

    async def read(
        self,
        path: str
    ) -> str:
        ...

    async def exists(
        self,
        path: str
    ) -> bool:
        ...

    async def list(
        self,
        path: str = ""
    ) -> list[str]:
        ...
```

调用方只依赖：

```python
await package.read("SKILL.md")
```

而不应该直接依赖：

```python
Path
open()
read_text()
```

文件系统访问逻辑只能存在于具体 Package 实现中。

路径解析必须限制在 Package root 内，禁止目录穿越。

---

## 6. Package 实现

### 6.1 FileSystemSkillPackage

第一阶段实现本地文件系统 Package。

例如：

```text
skills/
└── pdf/
    └── SKILL.md
```

对应：

```python
FileSystemSkillPackage(root)
```

调用：

```python
await package.read("SKILL.md")
```

实际读取：

```text
skills/pdf/SKILL.md
```

### 6.2 RemoteSkillPackage

Remote Package 进入设计预留，第一版可不实现。

例如：

```text
Remote Skill

https://example.com/skills/pdf/

├── SKILL.md
├── references/
└── scripts/
```

调用方式保持一致：

```python
await package.read("SKILL.md")
```

内部可以通过：

```text
HTTP
Git
Object Storage
```

等方式获取资源。

最终结构：

```text
SkillPackage

├── FileSystemSkillPackage
├── RemoteSkillPackage
└── Future Providers
```

---

## 7. SKILL.md 设计

### 7.1 文件结构

`SKILL.md` 由两部分组成：

```text
SKILL.md
├── YAML Frontmatter
│
└── Markdown Body
```

示例：

```markdown
---
name: pdf
description: Create and analyze PDF files.
---

# PDF Skill

## Instructions

...
```

### 7.2 Metadata

Frontmatter 提供 Skill 元信息：

```yaml
name:
description:
```

用于：

* Skill Resolve（组装期读取 Metadata）；
* Available Skills Context；
* Agent 判断是否需要 Skill。

`name`、`description` 为必填字段。建议对齐通用 Agent Skills 规范：`name` 使用小写字母、数字与连字符。

### 7.3 Instructions

Markdown Body 提供：

* 工作流程；
* 领域规则；
* 操作指导；
* 资源引用。

---

## 8. Progressive Disclosure

Skill 采用渐进式加载，不进行全量读取。

整体流程：

```text
Metadata
    ↓
SKILL.md Instructions
    ↓
Additional Resources
```

### 8.1 Level 1：Metadata

Agent 组装阶段只读取：

```text
SKILL.md Frontmatter
```

获取：

```text
name
description
```

例如：

```text
pdf:
Create and analyze PDF files.

coding:
Software development assistance.
```

此阶段不加载：

```text
Skill Instructions
references
scripts
assets
```

### 8.2 Level 2：Skill Instructions

Agent 判断当前任务需要某个 Skill：

```text
load_skill("pdf")
```

然后读取：

```text
pdf/SKILL.md
```

返回 Skill Instructions（Markdown Body）。

### 8.3 Level 3：Additional Resources

如果 Skill Instructions 中引用：

```text
references/specification.md
scripts/validate.py
assets/template.docx
```

再按需读取。第一版可不实现专用资源读取 Tool。

---

## 9. 配置：AgentConfig.skill_list

Skill 通过 `AgentConfig.skill_list` 声明。

类型：

```python
skill_list: dict[str, Any]
```

语义：

| 部分 | 含义 |
| --- | --- |
| key（`str`） | Skill 名称 |
| value（`Any`） | Skill 位置：本地 path 或远端 url |

示例：

```python
skill_list = {
    "pdf": "F:/skills/pdf",
    "coding": "https://example.com/skills/coding/",
}
```

说明：

1. Config 只声明可用 Skill 及其定位信息，不执行加载逻辑；
2. value 表示 Skill Package 根位置（其下包含 `SKILL.md`）；
3. 本地 path 对应 `FileSystemSkillPackage`；
4. 远端 url 对应 `RemoteSkillPackage`（第一版可暂不实现）。

---

## 10. Skill Descriptor

Skill Metadata 与 Package 关联。

定义：

```python
@dataclass(frozen=True)
class SkillDescriptor:

    name: str

    description: str

    package: SkillPackage
```

示例：

```text
SkillDescriptor

name:
pdf

description:
Create and analyze PDF files.

package:
FileSystemSkillPackage
```

远端：

```text
SkillDescriptor

name:
pdf

description:
Create and analyze PDF files.

package:
RemoteSkillPackage
```

两者对 Runtime 完全一致。

---

## 11. Skill Resolve

### 11.1 职责

Skill Resolve 根据 `skill_list` 构建可用 Skill 的只读映射。

输入：

```text
skill_list: dict[str, path | url]
```

输出：

```text
dict[str, SkillDescriptor]
```

### 11.2 流程

```text
skill_list

↓

遍历 (name, location)

↓

按 location 创建 SkillPackage
（path → FileSystemSkillPackage
 url  → RemoteSkillPackage）

↓

读取 SKILL.md Metadata

↓

生成 SkillDescriptor

↓

只读映射 name → SkillDescriptor
```

注意：

1. Resolve 阶段只读取 Metadata，不加载完整 Instructions；
2. 建议校验 frontmatter.`name` 与 `skill_list` 的 key 一致；
3. 映射为组装期产物，只读查找，不提供可变注册接口。

### 11.3 与 Package 解耦

Resolve 产出 `SkillDescriptor`，Descriptor 持有 `SkillPackage`。

上层始终通过 Descriptor / Package 访问资源，不直接依赖存储介质。

---

## 12. Available Skills Context

Agent 不直接加载所有 Skill 内容。

只提供 Metadata 级上下文：

```text
Available Skills:

- pdf:
  Create and analyze PDF files.

- coding:
  Software development assistance.
```

模型根据：

```text
用户请求
+
Available Skills
```

判断是否需要加载某个 Skill。

---

## 13. Skill Usage Prompt

### 13.1 定位

Skill 需要一段专用系统提示，用于约束「何时加载 Skill、如何使用加载结果」。

它与 `tool_call_policy` 类似，都是行为约束；但仅在存在可用 Skill 时注入，不作为全局无条件策略。

### 13.2 内容结构

Skill Usage Prompt 由两部分组成：

1. **固定规则**：何时 `load_skill`、如何对待返回的 Instructions、避免无必要重复加载；
2. **动态名单**：Available Skills（name + description）。

示例结构：

```text
# Skill Usage

When a task matches an available skill:
- Load the skill before performing specialized work in that domain.
- Treat the returned skill instructions as authoritative guidance.
- Do not invent skill content that has not been loaded.
- Avoid reloading the same skill unless necessary.

# Available Skills

- pdf: Create and analyze PDF files.
- coding: Software development assistance.
```

### 13.3 注入策略

| 位置 | 内容 | 条件 |
| --- | --- | --- |
| Action | Skill Usage 规则 + Available Skills | `skill_list` 非空 |
| Reason（可选） | 仅领域能力提示 + Available Skills，不提及具体 Tool 名 | `skill_list` 非空 |

说明：

1. `load_skill` 的 Tool Description 作为补充，不能替代 Skill Usage Prompt；
2. 不把完整 `SKILL.md` Body 写入系统提示；
3. 注入逻辑由组装层 / Prompt 组装完成，不修改 ReAct 图结构。

---

## 14. load_skill 能力设计

### 14.1 定位

`load_skill` 是 `echo-agent` 的一个能力。

实现形式：

```text
load_skill
    =
Tool
```

它不是：

* Skill Agent；
* Skill Resolver；
* Graph Node。

### 14.2 Tool 定义

```python
@tool
async def load_skill(
    name: str
) -> str:
    ...
```

说明：

1. 使用普通 `@tool` 定义；
2. 内部查找 Resolve 得到的只读映射；
3. 读取并返回对应 Skill 的 Instructions（Markdown Body）；
4. 未知 name 时返回明确错误，并给出可用 Skill 列表。

### 14.3 执行流程

```text
Agent

↓

load_skill("pdf")

↓

只读映射 name → SkillDescriptor

↓

Skill Package

↓

read("SKILL.md")

↓

解析 Instructions

↓

Tool Observation

↓

Agent
```

---

## 15. 与 Tool 系统集成

`echo-agent` 已存在：

```text
ToolDefinition
ToolRegistry
Tool Execution
```

因此：

```text
load_skill
```

直接复用现有 Tool 系统。

结构：

```text
ToolRegistry

├── Function Tools
├── MCP Tools
└── load_skill
```

执行流程保持一致：

```text
Tool Call

↓

Tool Execute

↓

Observation
```

第一版 `load_skill` 可作为普通 Function Tool 注册；如需观测分类，可再扩展 `ToolType`。

---

## 16. 与 ReAct 集成

Skill 不改变 ReAct。

流程：

```text
User Request

↓

Reason

↓

Action

├── load_skill()

└── Other Tools

↓

Observation

↓

Reason
```

示例：

```text
用户：
分析这个 PDF。

Reason：
需要 PDF 领域能力指导。

Action：
load_skill("pdf")

Observation：
PDF Skill Instructions

Reason：
根据 Skill 指导继续执行。
```

组装顺序建议：

```text
1. Resolve(skill_list) → 只读映射
2. 注册 load_skill 到 ToolRegistry
3. 注入 Skill Usage Prompt（含 Available Skills）
4. 创建 ReAct Subgraph
```

---

## 17. State 设计

第一版不增加 Skill State。

Skill 加载结果通过现有 Tool Message 进入下一轮模型调用。

流程：

```text
Action

↓

load_skill

↓

Observation

↓

Reason
```

后续若需要缓存、去重加载或生命周期管理，再引入：

```python
SkillState:

loaded_skills
```

---

## 18. 模块结构

第一版：

```text
echo_agent/core/capability/skill/

├── package.py
├── parser.py
├── descriptor.py
├── resolve.py
└── context.py

echo_agent/core/tool/toolkit/

└── skill.py          # load_skill Tool
```

职责：

| 文件 | 职责 |
| --- | --- |
| package.py | SkillPackage、FileSystemSkillPackage |
| parser.py | SKILL.md 解析 |
| descriptor.py | SkillDescriptor |
| resolve.py | 基于 skill_list 构建只读映射 |
| context.py | Skill Usage Prompt / Available Skills 文案 |
| toolkit/skill.py | load_skill Tool |

---

## 19. 实现计划

### Phase 1：基础模型

实现：

* SkillPackage；
* FileSystemSkillPackage；
* SKILL.md Parser。

### Phase 2：配置解析

实现：

* SkillDescriptor；
* Resolve（`skill_list` → 只读映射）。

### Phase 3：Agent 集成

实现：

* Skill Usage Prompt + Available Skills；
* load_skill Tool；
* ToolRegistry 注册；
* 组装期接入。

### Phase 4：资源加载

支持：

* references；
* scripts；
* assets。

### Phase 5：Remote Package

增加：

```text
RemoteSkillPackage
```

不修改：

* SkillDescriptor；
* load_skill；
* ReAct 流程。

---

## 20. 第一版范围

包含：

```text
Skill Package

↓

FileSystemSkillPackage

↓

skill_list Resolve

↓

Available Skills + Skill Usage Prompt

↓

load_skill Tool

↓

SKILL.md Instructions Loading

↓

ReAct Continue
```

不包含：

```text
Skill Agent

Skill Graph Node

目录扫描式自动发现

全量 Skill Loading

Remote Provider 实现

Skill 生命周期管理

Level 3 专用资源 Tool
```

---

## 21. 最终架构总结

```text
AgentConfig.skill_list
        │
        │  { name → path | url }
        ▼
     Resolve
        │
        ▼
  SkillDescriptor（只读映射）
        │
        ├──────────────────┐
        ▼                  ▼
 Skill Usage Prompt   load_skill Tool
 + Available Skills         │
        │                   ▼
        │            Skill Package
        │              /        \
        │          Local      Remote
        │              \        /
        │                SKILL.md
        │                   │
        ▼                   ▼
     Action ◄──── Tool Observation（Instructions）
        │
        ▼
     Reason
```

核心设计原则：

1. Skill 是 `echo-agent` 的一种能力；
2. Skill Package 是逻辑资源树，不是压缩包；
3. `SKILL.md` 是 Skill 唯一入口；
4. 默认采用 Progressive Disclosure；
5. `skill_list` 以 name → path/url 声明可用 Skill；
6. `load_skill` 是 Tool；
7. 复用现有 ToolRegistry；
8. SkillPackage 与存储介质解耦；
9. 有 Skill 时注入 Skill Usage Prompt；
10. 不引入 Skill Registry、Skill Agent、Skill Graph Node。
