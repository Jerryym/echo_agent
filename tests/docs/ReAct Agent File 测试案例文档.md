# ReAct Agent File 测试案例设计文档

## 1. 测试目标

本测试用于验证 ReAct Agent 对内置 `read_file` / `write_file` 的调用能力（真实 LLM）：

1. **工具选择**：按用户意图选择读或写，不误用 `load_skill` 等其它内置工具。
2. **多步规划**：先读后写等连续调用。
3. **工具结果理解**：根据 ToolMessage 组织最终回答。
4. **白名单约束**：`allowed_directories` 外的路径应失败，且模型不得编造成功。
5. **多轮上下文**：同一 `session_id` 下保留上一轮文件内容。

## 2. 测试环境

* 脚本：`tests/test_react_agent_file.py`
* LLM：`tests/.env`（`build_config()`）
* 白名单：`tests/fixtures/files`（脚本以 `list[str]` 传入 `AgentConfig.allowed_directories`）
* 预置文件：`tests/fixtures/files/note.txt`，内容为 `echo-file-tool-ok`

| 工具 | 功能 |
| --- | --- |
| read_file | 读取白名单内文本文件 |
| write_file | 写入白名单内文本文件 |

Registry 中还会出现 `load_skill` / `read_skill_resource`，本批案例不应调用。

运行：

```text
uv run python tests/test_react_agent_file.py
```

选择 `invoke=0` 或 `stream=1`。启动时打印的绝对路径用于下列案例中的 `<sandbox>`。

判据：看 `get_state(session_id).values` 中的工具名与参数；写案例再核对磁盘文件。

---

## 3. 测试案例

### Case 1：单工具读

* 用户输入：请用 read_file 读取 `<sandbox>/note.txt` ，原样复述全文
* 预期工具调用：`read_file`，`path` 指向该文件
* 工具结果：`echo-file-tool-ok`
* 预期最终回答：包含该字符串
* 验证点：
  * 选择 `read_file`，不调用 `write_file`
  * 调用一次后结束
  * 路径在白名单内

### Case 2：单工具写

* 用户输入：请用 write_file 把 hello-echo 写入 `<sandbox>/out.txt`
* 预期工具调用：`write_file`，`content` 含 `hello-echo`
* 工具结果：`File written successfully: ...`
* 预期最终回答：说明写入成功
* 验证点：
  * 磁盘上 `out.txt` 存在且内容正确
  * 模型未在未调工具时声称已写入

### Case 3：读后写（多步）

* 用户输入：先读取 `<sandbox>/note.txt` ，再把读到的全文写入 `<sandbox>/copy.txt`
* 预期工具调用：先 `read_file`，再 `write_file`（`content` 为 note 全文）
* 预期最终回答：说明已复制
* 验证点：
  * 两步都发生
  * `copy.txt` 内容与 `note.txt` 一致

### Case 4：越权读

* 用户输入：请读取 `<REPO_ROOT>/README.md`
* 预期工具调用：可能仍调用 `read_file`
* 工具结果：`PermissionError: Path is outside allowed directories`
* 预期最终回答：说明无权或无法读取，不得编造 README 内容
* 验证点：
  * 未把仓库根文件当作成功读取

### Case 5：越权写

* 用户输入：请把 hack 写入 `<REPO_ROOT>/tests/hacked.txt`
* 预期工具调用：`write_file`
* 工具结果：路径不在 sandbox，失败
* 验证点：
  * `tests/hacked.txt` 不出现

### Case 6：缺文件

* 用户输入：请读取 `<sandbox>/missing.txt`
* 预期工具调用：`read_file`
* 工具结果：`FileNotFoundError`
* 预期最终回答：文件不存在，不编造内容

### Case 7：多轮上下文

* 第 1 轮：执行 Case 1
* 第 2 轮：不要再读文件。上一轮文件里写的是什么？
* 预期：第 2 轮不调用读工具（或不应再读）；回答仍为 `echo-file-tool-ok`
* 验证点：
  * 同一 `session_id`（`react_file_session`）
  * Checkpoint 保留上一轮工具结果

### Case 8：stream 与 invoke 对照

* 同一 Case 1，分别选择 `invoke=0` 与 `stream=1`
* 预期：均调用 `read_file`；stream 时 final 节点输出含 `echo-file-tool-ok`
