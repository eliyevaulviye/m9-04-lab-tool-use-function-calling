"""
Lab | Give the Model Hands
---------------------------
Two tools (lookup_order, calculate) are described to a Gemini model via
native function calling. The model can only *request* a tool call; this
script is responsible for validating the arguments, running the real
function, and feeding the result back to the model. The loop continues
until the model produces a final, tool-free answer.

Uses the current `google-genai` SDK (the old `google-generativeai` package
is deprecated).

Run:
    pip install -r requirements.txt
    # put GOOGLE_API_KEY=your-key in a .env file, OR export it directly
    python tool_use_lab.py
"""

import ast
import json
import operator
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()  # reads a .env file in the current directory, if present

ORDERS_PATH = Path(__file__).parent / "orders.json"
TRANSCRIPT_PATH = Path(__file__).parent / "transcript.md"

API_KEY = os.environ.get("GOOGLE_API_KEY")
if not API_KEY:
    sys.exit(
        "ERROR: GOOGLE_API_KEY not found. Either export it in your shell, "
        "or create a .env file (in the same folder as this script) "
        "containing a line: GOOGLE_API_KEY=your-key-here"
    )

client = genai.Client(api_key=API_KEY)

with open(ORDERS_PATH, "r", encoding="utf-8") as f:
    ORDERS_DB = json.load(f)


# ---------------------------------------------------------------------------
# Tool implementations (the "hands")
# ---------------------------------------------------------------------------

def lookup_order(order_id: str) -> dict:
    """Return the stored details for a given order id, or a not-found message."""
    order = ORDERS_DB.get(order_id.upper())
    if order is None:
        return {"found": False, "error": f"Order '{order_id}' was not found."}
    return {"found": True, **order}


_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    """Recursively evaluate an arithmetic AST node, allowing only numbers
    and +, -, *, /, ** operators. This avoids using a raw eval() on
    model-supplied text."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](
            _safe_eval(node.left), _safe_eval(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Expression contains unsupported syntax.")


def calculate(expression: str) -> dict:
    """Safely evaluate a simple arithmetic expression and return the result."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": f"Could not evaluate '{expression}': {exc}"}


AVAILABLE_FUNCTIONS = {
    "lookup_order": lookup_order,
    "calculate": calculate,
}


# ---------------------------------------------------------------------------
# Tool schema (what the model is told about the tools)
# ---------------------------------------------------------------------------

lookup_order_decl = types.FunctionDeclaration(
    name="lookup_order",
    description=(
        "Look up a customer order by its order id and return the item "
        "name, price, purchase date, and warranty length in months. "
        "Returns an error message if the order id does not exist."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "order_id": types.Schema(
                type="STRING",
                description="The order id, e.g. 'A1001'.",
            )
        },
        required=["order_id"],
    ),
)

calculate_decl = types.FunctionDeclaration(
    name="calculate",
    description=(
        "Evaluate a simple arithmetic expression (numbers combined with "
        "+, -, *, /, ** and parentheses) and return the exact numeric "
        "result. Use this for any math instead of computing it yourself."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "expression": types.Schema(
                type="STRING",
                description="Arithmetic expression, e.g. '1200 * 3'.",
            )
        },
        required=["expression"],
    ),
)

tools = types.Tool(function_declarations=[lookup_order_decl, calculate_decl])

# Automatic function calling is turned off on purpose: the whole point of
# this lab is that WE (not the SDK) intercept each tool call, validate it,
# run it, and send the result back.
config = types.GenerateContentConfig(
    tools=[tools],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)

MODEL_NAME = "gemini-flash-latest"


# ---------------------------------------------------------------------------
# The model -> tool -> model loop
# ---------------------------------------------------------------------------

def run_conversation(prompt: str, log: list) -> str:
    """Send `prompt` to the model and run the tool-use loop until a final
    text answer is produced. Every tool call and its arguments/result is
    appended to `log` so the loop is visible afterwards."""

    chat = client.chats.create(model=MODEL_NAME, config=config)

    log.append(f"\n### USER\n{prompt}\n")
    response = chat.send_message(prompt)

    while True:
        function_calls = response.function_calls  # convenience property

        if not function_calls:
            final_text = response.text
            log.append(f"### MODEL (final answer)\n{final_text}\n")
            return final_text

        # The model asked for one or more tool calls. Validate + execute each.
        response_parts = []
        for call in function_calls:
            name = call.name
            args = dict(call.args) if call.args else {}

            log.append(
                f"### TOOL CALL REQUESTED BY MODEL\n"
                f"- function: `{name}`\n"
                f"- arguments: `{json.dumps(args)}`\n"
            )

            if name not in AVAILABLE_FUNCTIONS:
                result = {"error": f"Unknown tool '{name}' requested by model."}
            else:
                try:
                    result = AVAILABLE_FUNCTIONS[name](**args)
                except TypeError as exc:
                    result = {"error": f"Invalid arguments for '{name}': {exc}"}

            log.append(f"### TOOL RESULT\n`{json.dumps(result)}`\n")

            response_parts.append(
                types.Part.from_function_response(name=name, response={"result": result})
            )

        # Feed every tool result back to the model in one turn and continue
        # the loop in case it needs another tool call.
        response = chat.send_message(response_parts)


# ---------------------------------------------------------------------------
# Demo questions
# ---------------------------------------------------------------------------

def main():
    log = ["# Tool-Use Transcript\n"]

    print("=" * 70)
    print("Q1 (needs BOTH tools, chained): order lookup -> calculate")
    print("=" * 70)
    answer1 = run_conversation(
        "For order A1001, what would the total be if I bought three of them?",
        log,
    )
    print("\nFINAL ANSWER:", answer1)

    print("\n" + "=" * 70)
    print("Q2 (needs NO tool): general question")
    print("=" * 70)
    answer2 = run_conversation("What can you help me with?", log)
    print("\nFINAL ANSWER:", answer2)

    print("\n" + "=" * 70)
    print("Q3 (stretch): bad order id, lookup_order should fail gracefully")
    print("=" * 70)
    answer3 = run_conversation(
        "Can you tell me the price and warranty for order A9999?",
        log,
    )
    print("\nFINAL ANSWER:", answer3)

    TRANSCRIPT_PATH.write_text("\n".join(log), encoding="utf-8")
    print(f"\nFull transcript written to {TRANSCRIPT_PATH}")


if __name__ == "__main__":
    main()
