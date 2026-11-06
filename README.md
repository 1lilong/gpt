# gptchat

A terminal chatbot for OpenAI and OpenAI-compatible chat APIs. The current session keeps the conversation, streams the reply when the endpoint supports it, and falls back to a single response when it does not.

[English](#english) · [中文](#中文)

---

## English

### Install

Python 3.10 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run it from the project directory:

```bash
python -m gptchat
```

To install the `gptchat` command on your `PATH`:

```bash
pip install .
gptchat
```

### Configure

The API key is read from the environment. gptchat does not contain a key and does not load a `.env` file on its own.

```bash
export OPENAI_API_KEY="sk-..."
```

Optional:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API root, including `/v1` when the server uses that prefix |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model id sent with every request |

A template lives in [`.env.example`](.env.example). Load it in the shell if you want a file:

```bash
cp .env.example .env
# edit .env, then:
set -a && source .env && set +a
```

On Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
$env:OPENAI_MODEL = "gpt-4o-mini"
python -m gptchat
```

The same variables work with compatible servers. The value of `OPENAI_API_KEY` can be any non-empty string when the server ignores it.

```bash
# Ollama
export OPENAI_BASE_URL="http://127.0.0.1:11434/v1"
export OPENAI_API_KEY="ollama"
export OPENAI_MODEL="llama3.2"

# OpenRouter
export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export OPENAI_API_KEY="sk-or-..."
export OPENAI_MODEL="openai/gpt-4o-mini"
```

Flags override the environment for one process:

```bash
python -m gptchat --model gpt-4o --system "Answer in one sentence."
python -m gptchat --base-url http://127.0.0.1:11434/v1 --no-stream
```

### Usage

Each line is one message. gptchat sends the system prompt (when one is set) and the full conversation from this process.

```text
You › Explain TCP in one sentence
Assistant › TCP is a connection-oriented protocol that delivers a reliable byte stream between two programs.

You › /exit
Goodbye.
```

Up-arrow history is available in an interactive terminal when Python's `readline` module is installed (it is, on macOS and Linux).

What you type is sent to the endpoint in `OPENAI_BASE_URL`. The transcript stays in memory for this process only. Closing the program clears it.

Exit codes: `0` after a normal exit, `1` when the key or the URL/model setting is unusable.

### Commands

| Command | Action |
| --- | --- |
| `/help` | Show the commands |
| `/reset` | Clear conversation history. The system prompt stays. |
| `/model` | Show the current model |
| `/model <name>` | Use `<name>` for the following requests |
| `/system` | Show the system prompt |
| `/system <text>` | Replace the system prompt and keep the current history |
| `/system --clear` | Remove the system prompt |
| `/exit`, `/quit` | Leave gptchat |
| `//...` | Send the rest as a message, including a leading slash. `//reset` sends the text `/reset`. |

Ctrl+C during a reply stops generation and keeps whatever text already arrived. Ctrl+C at the prompt, and Ctrl+D (Ctrl+Z on Windows), leave the program.

### Streaming

gptchat asks for a streamed reply. Tokens are printed as they arrive. When the endpoint rejects streaming, or returns one JSON completion instead of a server-sent event stream, gptchat prints that reply and uses a single response for the rest of the session. `--no-stream` skips the streamed request.

### Troubleshooting

- **`OPENAI_API_KEY is not set`** — export the variable in the same shell that starts gptchat.
- **Authentication failed** — the endpoint rejected the key. Confirm the key belongs to the account for `OPENAI_BASE_URL`.
- **Could not connect** — the base URL is unreachable, or it is missing the `/v1` prefix the server expects.
- **HTTP 404** — `OPENAI_BASE_URL` should be the API root (`https://api.openai.com/v1`), not the full `/chat/completions` path.
- **The model name was rejected** — set `OPENAI_MODEL` or `/model` to an id that server offers.

### Tests

The tests start a local fake API. They do not call OpenAI.

```bash
python -m unittest discover -s tests -v
```

---

## 中文

终端里的多轮聊天程序，对接 OpenAI 以及兼容 OpenAI Chat Completions 的接口。当前进程会记住对话；接口支持流式输出时逐段显示，不支持时自动改为一次返回整段回复。

### 安装

需要 Python 3.10 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate   # Windows：.venv\Scripts\activate
pip install -r requirements.txt
```

在项目目录中启动：

```bash
python -m gptchat
```

如果希望在任意目录使用 `gptchat` 命令：

```bash
pip install .
gptchat
```

### 配置

密钥只从环境变量读取。程序里没有内置密钥，也不会自动加载 `.env` 文件。

```bash
export OPENAI_API_KEY="sk-..."
```

可选变量：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 接口根地址。服务端带 `/v1` 前缀时，这里也要带上 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 每次请求使用的模型 id |

仓库里的 [`.env.example`](.env.example) 是模板。需要文件时，在 shell 里自己加载：

```bash
cp .env.example .env
# 编辑 .env 后：
set -a && source .env && set +a
```

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
$env:OPENAI_MODEL = "gpt-4o-mini"
python -m gptchat
```

兼容服务使用同一组变量。服务端不校验密钥时，`OPENAI_API_KEY` 填任意非空字符串即可。

```bash
# Ollama
export OPENAI_BASE_URL="http://127.0.0.1:11434/v1"
export OPENAI_API_KEY="ollama"
export OPENAI_MODEL="llama3.2"

# OpenRouter
export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export OPENAI_API_KEY="sk-or-..."
export OPENAI_MODEL="openai/gpt-4o-mini"
```

命令行参数只对这一次进程生效，并覆盖环境变量：

```bash
python -m gptchat --model gpt-4o --system "用一句话回答。"
python -m gptchat --base-url http://127.0.0.1:11434/v1 --no-stream
```

### 使用

一行是一条消息。程序会带上系统提示（如果设置了）以及本次进程里的全部对话。

```text
You › 用一句话说明 TCP
Assistant › TCP 是面向连接的协议，在两个程序之间提供可靠的字节流。

You › /exit
Goodbye.
```

在交互式终端中，如果 Python 自带 `readline`（macOS 和 Linux 通常有），可以用上方向键翻看输入过的行。

你输入的内容会发送到 `OPENAI_BASE_URL` 指向的服务。记录只留在当前进程的内存里，退出后即消失。

退出码：正常离开是 `0`；密钥、地址或模型设置无法使用时是 `1`。

### 命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示命令 |
| `/reset` | 清空对话记录，系统提示保留 |
| `/model` | 显示当前模型 |
| `/model <name>` | 之后的请求改用这个模型 |
| `/system` | 显示系统提示 |
| `/system <text>` | 更换系统提示，并保留当前对话 |
| `/system --clear` | 去掉系统提示 |
| `/exit`、`/quit` | 退出 |
| `//...` | 把这一行当作普通消息发送，可以带上开头的斜杠。`//reset` 会发送文本 `/reset` |

回复生成过程中按 Ctrl+C 会停在已经收到的文字，并把这段不完整回复留在本次对话里。在输入提示处按 Ctrl+C，或按 Ctrl+D（Windows 上是 Ctrl+Z），会离开程序。

### 流式输出

程序默认请求流式回复，文字到达后立刻显示。如果接口拒绝流式参数，或者在要求流式时仍返回一整段 JSON，程序会先把这段回复打印出来，随后本次会话都改为一次取回整段。`--no-stream` 会跳过流式请求。

### 故障排除

- **`OPENAI_API_KEY is not set`**：在启动 gptchat 的同一个 shell 里导出该变量。
- **Authentication failed**：接口拒绝了密钥。确认密钥属于 `OPENAI_BASE_URL` 对应的账户。
- **Could not connect**：基地址无法连接，或少写了服务端要求的 `/v1`。
- **HTTP 404**：`OPENAI_BASE_URL` 应是接口根路径（`https://api.openai.com/v1`），不要写成完整的 `/chat/completions`。
- **模型名被拒绝**：把 `OPENAI_MODEL` 或 `/model` 设成该服务实际提供的 id。

### 测试

测试会在本机启动一个假的接口，不会访问 OpenAI。

```bash
python -m unittest discover -s tests -v
```
