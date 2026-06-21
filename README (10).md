# Lab | Give the Model Hands

Two tools — `lookup_order` and `calculate` — are described to a Gemini model
via native function calling. The model can only *request* a tool call; the
Python code validates the arguments, runs the real function, and feeds the
result back to the model until it produces a final answer.

## Files

- `orders.json` — tiny order database (5 sample orders).
- `tool_use_lab.py` — all the code: tool implementations, schemas, and the
  model → tool → model loop. Built on the current `google-genai` SDK
  (the older `google-generativeai` package is deprecated). Running it
  asks three questions:
  1. A two-tool, chained question (`lookup_order` → `calculate`).
  2. A no-tool question (general "what can you help me with").
  3. A stretch question with a non-existent order id (`A9999`), to show
     graceful error handling.
- `transcript.md` — generated automatically the first time you run the
  script. Shows every tool call (name + arguments) and every final answer.
- `requirements.txt` — Python dependencies.

## Setup

```bash
pip install -r requirements.txt
```

Provide your API key one of two ways:

**Option A — .env file (recommended for Windows/PowerShell):**
Create a file named `.env` in this folder (copy `.env.example`) containing:
```
GOOGLE_API_KEY=your-free-gemini-key
```
`tool_use_lab.py` loads it automatically via `python-dotenv`.

**Option B — environment variable:**
```bash
# macOS/Linux
export GOOGLE_API_KEY="your-free-gemini-key"

# Windows PowerShell
$env:GOOGLE_API_KEY="your-free-gemini-key"
```

Then run:
```bash
python tool_use_lab.py
```

After it runs, open `transcript.md` to see the full tool-call log next to
the model's final answers — that's your submission evidence.

## How the loop works

1. `chat.send_message(prompt)` sends the user's question along with the two
   tool schemas.
2. If the model's response contains a `function_call` part, the code reads
   `call.name` and `call.args`, runs the matching local Python function, and
   wraps the result in a `FunctionResponse`.
3. That result is sent back with `chat.send_message(...)`.
4. Steps 2–3 repeat until the model responds with plain text and no further
   function calls — that text is the final answer.

This is why the two-tool question (e.g. "order A1001, total for 3 of them")
makes the loop run twice: first `lookup_order` to get the price, then
`calculate` to multiply it by 3.

## No API key is committed

`GOOGLE_API_KEY` is read from the environment only — never hard-coded or
written to any file in this repo.
