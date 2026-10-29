from __future__ import annotations

import ast
import base64
import hmac
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
APP_VERSION = "2.1.0"
NODE_STARTED_MONOTONIC = time.monotonic()
DATA_DIR = ROOT / "data"
NOTES_PATH = DATA_DIR / "notes.json"
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 20_000
MAX_NOTE_LENGTH = 600
SAFE_SITES = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "spotify": "https://open.spotify.com/",
    "github": "https://github.com/",
    "wikipedia": "https://www.wikipedia.org/",
    "maps": "https://maps.google.com/",
}
PORT = DEFAULT_PORT


def load_dotenv() -> None:
    """Read this project's optional .env without adding a dependency."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key in {"OPENAI_API_KEY", "JARVIS_MODEL", "JARVIS_PORT"} and value:
            os.environ.setdefault(key, value)


def read_port() -> int:
    try:
        raw_value = os.environ.get("PORT") or os.environ.get("JARVIS_PORT") or str(DEFAULT_PORT)
        value = int(raw_value)
        return value if 1 <= value <= 65535 else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def browser_notes_enabled() -> bool:
    return os.environ.get("JARVIS_NOTES_MODE", "server").strip().casefold() == "browser"


def read_notes() -> list[dict[str, str]]:
    try:
        raw = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        notes = []
        for item in raw[-100:]:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                notes.append({
                    "id": str(item.get("id", ""))[:32],
                    "text": item["text"][:MAX_NOTE_LENGTH],
                    "created": str(item.get("created", ""))[:40],
                })
        return notes
    except (OSError, json.JSONDecodeError):
        return []


def write_notes(notes: list[dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = NOTES_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(notes[-100:], ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(NOTES_PATH)


def add_note(text: str) -> dict[str, str]:
    clean = re.sub(r"\s+", " ", text).strip()[:MAX_NOTE_LENGTH]
    if not clean:
        raise ValueError("A note needs some text.")
    note = {
        "id": secrets.token_hex(5),
        "text": clean,
        "created": datetime.now().astimezone().isoformat(timespec="minutes"),
    }
    notes = read_notes()
    notes.append(note)
    write_notes(notes)
    return note


NUMBER_WORDS = {
    "zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
NUMBER_SCALES = {
    "hundred": 100, "thousand": 1_000, "lakh": 100_000, "lac": 100_000,
    "lekh": 100_000, "lack": 100_000, "lak": 100_000,
    "crore": 10_000_000, "cr": 10_000_000, "million": 1_000_000, "billion": 1_000_000_000,
}
_NUMBER_TOKEN = "|".join(sorted(
    [*NUMBER_WORDS, *NUMBER_SCALES, "hundreds", "thousands", "lakhs", "lacs", "lekhs", "lacks", "laks", "crores", "millions", "billions"],
    key=len,
    reverse=True,
))
NUMBER_WORD_PATTERN = re.compile(
    rf"\b(?:{_NUMBER_TOKEN})(?:(?:[\s-]+and)?[\s-]+(?:{_NUMBER_TOKEN}))*\b",
    re.IGNORECASE,
)


def spoken_number_value(phrase: str) -> int:
    total = 0
    current = 0
    for token in re.findall(r"[a-z]+", phrase.casefold()):
        if token == "and":
            continue
        if token in NUMBER_WORDS:
            current += NUMBER_WORDS[token]
            continue
        scale = NUMBER_SCALES.get(token.rstrip("s"))
        if scale is None:
            raise ValueError("I couldn't understand that number.")
        if scale == 100:
            current = max(current, 1) * scale
        else:
            total += max(current, 1) * scale
            current = 0
    return total + current


def normalize_calculation(expression: str) -> str:
    text = expression.strip().replace(",", "")
    text = re.sub(r"\b(?:multiply|multiplying|multiplies|multiplied)(?:\s+by)?\b|\b(?:times|into)\b", " * ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:divided|divide|dividing)(?:\s+by)?\b", " / ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bplus\b", " + ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bminus\b", " - ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:to\s+the\s+power\s+of|power\s+of)\b", " ** ", text, flags=re.IGNORECASE)
    text = text.replace("\u00d7", "*").replace("\u00f7", "/")

    scales = {
        "thousand": 1_000, "thousands": 1_000, "lakh": 100_000, "lakhs": 100_000,
        "lac": 100_000, "lacs": 100_000, "crore": 10_000_000, "crores": 10_000_000,
        "lekh": 100_000, "lekhs": 100_000, "lack": 100_000, "lacks": 100_000,
        "lak": 100_000, "laks": 100_000,
        "cr": 10_000_000, "million": 1_000_000, "millions": 1_000_000,
        "billion": 1_000_000_000, "billions": 1_000_000_000,
    }
    scale_pattern = re.compile(
        r"(?<![\w.])(\d+(?:\.\d+)?)\s*(thousands?|lakhs?|lacs?|crores?|cr|millions?|billions?)\b",
        re.IGNORECASE,
    )
    text = scale_pattern.sub(
        lambda match: "(" + format(float(match.group(1)) * scales[match.group(2).casefold()], ".15g") + ")",
        text,
    )
    text = NUMBER_WORD_PATTERN.sub(
        lambda match: "(" + str(spoken_number_value(match.group(0))) + ")",
        text,
    )
    text = re.sub(r"(?<=[)\d])\s+and\s+(?=[(\d])", " + ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=[)\d])\s*[xX]\s*(?=[\d(])", " * ", text)
    return text.strip().rstrip("?").strip()


def format_calculation_result(value: int | float) -> str:
    if isinstance(value, int):
        rendered = str(value)
    elif value.is_integer():
        rendered = str(int(value))
    else:
        rendered = format(value, ".15f").rstrip("0").rstrip(".")
    sign = "-" if rendered.startswith("-") else ""
    rendered = rendered.lstrip("-")
    whole, separator, fraction = rendered.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while head:
            pairs.append(head[-2:])
            head = head[:-2]
        whole = ",".join(reversed(pairs)) + "," + tail
    return sign + whole + (separator + fraction if fraction else "")


def number_to_words(value: int | float) -> str:
    units = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    def below_thousand(number: int) -> str:
        parts: list[str] = []
        if number >= 100:
            parts.extend((units[number // 100], "hundred"))
            number %= 100
        if number >= 20:
            parts.append(tens[number // 10])
            if number % 10:
                parts.append(units[number % 10])
        elif number >= 10:
            parts.append(teens[number - 10])
        elif number:
            parts.append(units[number])
        return " ".join(parts) if parts else "zero"

    def integer_words(number: int) -> str:
        if number < 1_000:
            return below_thousand(number)
        for scale, label in ((100_000_000_000, "kharab"), (1_000_000_000, "arab"),
                             (10_000_000, "crore"), (100_000, "lakh"), (1_000, "thousand")):
            if number >= scale:
                quotient, remainder = divmod(number, scale)
                phrase = integer_words(quotient) + " " + label
                return phrase + (" " + integer_words(remainder) if remainder else "")
        return below_thousand(number)

    rendered = format_calculation_result(value).replace(",", "")
    negative = rendered.startswith("-")
    if negative:
        rendered = rendered[1:]
    whole, separator, fraction = rendered.partition(".")
    phrase = integer_words(int(whole or "0"))
    if separator and fraction:
        phrase += " point " + " ".join(units[int(digit)] for digit in fraction)
    return ("minus " if negative else "") + phrase


def calculate(expression: str) -> str:
    expression = normalize_calculation(expression).replace("^", "**")
    if not expression or len(expression) > 100:
        raise ValueError("Give me a short arithmetic expression, such as 12 * (8 + 3).")
    if re.search(r"\)\s*\(", expression):
        raise ValueError("I heard two values without an operation between them. Add + or ×, for example “20 lakh plus 9 lakh.”")
    if re.match(r"^[*/]", expression) or re.search(r"[+\-*/]$", expression):
        raise ValueError("That calculation is missing a number. For example, say “calculate 1 lakh into 2,000.”")
    tree = ast.parse(expression, mode="eval")
    allowed_binary = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    allowed_unary = (ast.UAdd, ast.USub)
    nodes = list(ast.walk(tree))
    if len(nodes) > 40:
        raise ValueError("That expression is too long.")

    def visit(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if abs(node.value) > 1e12:
                raise ValueError("That number is outside the calculator's safe range.")
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, allowed_unary):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, allowed_binary):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("For safety, the exponent must be between -8 and 8.")
            result = {
                ast.Add: lambda: left + right,
                ast.Sub: lambda: left - right,
                ast.Mult: lambda: left * right,
                ast.Div: lambda: left / right,
                ast.FloorDiv: lambda: left // right,
                ast.Mod: lambda: left % right,
                ast.Pow: lambda: left ** right,
            }[type(node.op)]()
            if not isinstance(result, (int, float)) or not math.isfinite(float(result)) or abs(result) > 1e18:
                raise ValueError("That result is outside the calculator's safe range.")
            return result
        raise ValueError("I can calculate basic arithmetic only. Try 12 * (8 + 3).")

    try:
        value = visit(tree)
    except ZeroDivisionError as exc:
        raise ValueError("Division by zero is undefined.") from exc
    return format_calculation_result(value)


def timer_action(message: str) -> dict[str, object] | None:
    if not re.search(r"\b(timer|countdown)\b", message, re.IGNORECASE):
        return None
    matches = re.findall(
        r"\b(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b",
        message,
        re.IGNORECASE,
    )
    if not matches:
        return None
    seconds = 0
    for amount, unit in matches:
        unit = unit.lower()
        factor = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        seconds += int(amount) * factor
    if seconds < 1 or seconds > 86_400:
        return {"type": "timer_error", "message": "Timers can run from 1 second up to 24 hours."}
    label_parts = []
    for amount, unit in matches:
        label_parts.append(amount + " " + unit)
    return {"type": "timer", "seconds": seconds, "label": " ".join(label_parts)}


def local_command(message: str) -> dict[str, object] | None:
    clean = re.sub(r"^\s*(?:(?:hey|hello|hi)\s+)?jarvis[\s,:-]*", "", message, flags=re.IGNORECASE).strip()
    lower = clean.casefold()
    if not clean:
        return {"reply": "Hello. All systems are ready. What would you like to do?", "action": None, "source": "local"}

    if re.fullmatch(r"(hi|hello|hey|good morning|good afternoon|good evening|how are you)[.!? ]*", lower):
        return {"reply": "All systems are ready. What would you like to do?", "action": None, "source": "local"}

    if re.search(r"\b(?:i love you|love you|i like you|you(?:'re| are) (?:great|awesome|the best))\b", lower):
        return {"reply": "That’s kind of you. I’m glad I can help. What shall we work on next?", "action": None, "source": "local"}

    mode_match = re.fullmatch(
        r"(?:yes[, ]+)?(?:switch|change)(?:\s+(?:(?:conversation\s+)?mode))?"
        r"(?:\s+(?:to\s+)?(openai|ai|cloud|local|on-device))?(?:\s+mode)?[.! ]*",
        lower,
    )
    if mode_match:
        target_mode = "local" if mode_match.group(1) in {"local", "on-device"} else "openai"
        if target_mode == "local":
            return {
                "reply": "Switched to Local mode. Built-in commands and notes stay on this device.",
                "action": {"type": "set_mode", "mode": "local"},
                "source": "local",
            }
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            return {
                "reply": "OpenAI mode needs an API key. Add it to this project’s .env file and restart J.A.R.V.I.S.",
                "action": None,
                "source": "local",
            }
        return {
            "reply": "Switched to OpenAI mode. Open-ended prompts use your configured API key and require API credits; built-in commands still run locally.",
            "action": {"type": "set_mode", "mode": "openai"},
            "source": "local",
        }

    if re.search(r"\b(?:invalid syntax|calculator error|calculation error)\b", lower):
        return {
            "reply": "That was a calculator parsing bug: it treated Indian number scales as code. I fixed it to understand lakh, crore, and spoken “into” as multiplication.",
            "action": None,
            "source": "local",
        }
    if re.search(r"\b(help|what can you do|commands|capabilities)\b", lower):
        return {
            "reply": (
                "I can tell you the local time and date, calculate arithmetic, save and list notes, "
                "start a timer, open a few trusted sites, and speak replies aloud. "
                "Add an OpenAI API key in the project’s .env file for open-ended AI chat."
            ),
            "action": None,
            "source": "local",
        }

    if re.search(r"\b(time|clock)\b", lower):
        now = datetime.now().astimezone()
        return {"reply": "It’s " + now.strftime("%I:%M %p").lstrip("0") + " on your device.", "action": None, "source": "local"}

    if re.search(r"\b(date|day|today)\b", lower) and not re.search(r"\b(update|news)\b", lower):
        today = datetime.now().astimezone()
        return {"reply": "Today is " + today.strftime("%A, %B") + " " + str(today.day) + ", " + str(today.year) + ".", "action": None, "source": "local"}

    note_match = re.match(r"^(?:remember(?: that)?|save (?:a )?note(?: that)?|note that)\s+(.+)$", clean, re.IGNORECASE)
    if note_match:
        if browser_notes_enabled():
            note_text = re.sub(r"\s+", " ", note_match.group(1)).strip()[:MAX_NOTE_LENGTH]
            if not note_text:
                return {"reply": "A note needs some text.", "action": None, "source": "local"}
            return {
                "reply": "Saved to this browser’s Memory Vault: “" + note_text + "”",
                "action": {"type": "notes_save_browser", "text": note_text},
                "source": "local",
            }
        try:
            note = add_note(note_match.group(1))
        except (ValueError, OSError) as exc:
            return {"reply": "I couldn’t save that note: " + str(exc), "action": None, "source": "local"}
        return {
            "reply": "Saved to this device’s Memory Vault: “" + note["text"] + "”",
            "action": {"type": "notes_refresh"},
            "source": "local",
        }

    if re.search(r"\b(list|show|read)\b.*\b(notes|memory)\b|\bwhat do you remember\b", lower):
        if browser_notes_enabled():
            return {"reply": "Here are the notes saved in this browser’s Memory Vault.", "action": {"type": "show_memory"}, "source": "local"}
        notes = read_notes()
        if not notes:
            return {"reply": "Your Memory Vault is empty. Say “remember …” or add a note in Memory Vault.", "action": {"type": "show_memory"}, "source": "local"}
        listing = "\n".join("• " + item["text"] for item in notes[-8:])
        return {"reply": "Here are the latest notes saved on this device:\n" + listing, "action": {"type": "show_memory"}, "source": "local"}

    calc_match = re.match(r"^(?:calculate|compute|what is|what's|solve)\s+(.+?)\??$", clean, re.IGNORECASE)
    if calc_match and (re.search(r"\d", calc_match.group(1)) or NUMBER_WORD_PATTERN.search(calc_match.group(1))):
        try:
            answer = calculate(calc_match.group(1))
            return {"reply": "That comes to " + answer + ".", "action": None, "source": "local"}
        except SyntaxError:
            return {"reply": "I couldn't read that calculation. Try a phrase like “calculate 1 lakh into 2000” or use +, -, *, and /.", "action": None, "source": "local"}
        except (ValueError, OverflowError) as exc:
            return {"reply": str(exc), "action": None, "source": "local"}

    if (
        (re.fullmatch(r"[\d\s.+\-*/()%^]+", clean) and re.search(r"\d", clean))
        or (
            NUMBER_WORD_PATTERN.search(clean)
            and re.search(
                r"\b(?:plus|minus|times|into|multiply|multiplying|multiplies|multiplied|divided|divide|dividing)\b|"
                r"(?<!\w)[+*/×÷-](?!\w)|\bx\b",
                clean,
                re.IGNORECASE,
            )
        )
    ):
        try:
            answer = calculate(clean)
            return {"reply": "That comes to " + answer + ".", "action": None, "source": "local"}
        except SyntaxError:
            return {"reply": "I couldn't read that calculation. Try a phrase like “calculate 1 lakh into 2000” or use +, -, *, and /.", "action": None, "source": "local"}
        except (ValueError, OverflowError) as exc:
            return {"reply": str(exc), "action": None, "source": "local"}

    timer = timer_action(clean)
    if timer:
        if timer["type"] == "timer_error":
            return {"reply": str(timer["message"]), "action": timer, "source": "local"}
        return {
            "reply": "Timer set for " + str(timer["label"]) + ". I’ll alert you while this tab stays open.",
            "action": timer,
            "source": "local",
        }

    site_match = re.search(r"\bopen\s+(youtube|google|spotify|github|wikipedia|maps)\b", lower)
    if site_match:
        site = site_match.group(1)
        return {
            "reply": "Opening " + site.title() + ".",
            "action": {"type": "open_site", "url": SAFE_SITES[site]},
            "source": "local",
        }

    if re.search(r"\b(system|status|online|health)\b", lower):
        ai_ready = bool(os.environ.get("OPENAI_API_KEY", "").strip())
        mode = "OpenAI chat is configured" if ai_ready else "local command mode is active"
        return {"reply": "J.A.R.V.I.S. is online. " + mode + ". Notes are stored on this device.", "action": None, "source": "local"}

    return None


def read_calculation_follow_up(message: str, history: object) -> dict[str, object] | None:
    lower = message.casefold()
    asks_to_read = re.search(r"\b(?:read|say|speak|spell(?:\s+out)?)\b", lower)
    refers_to_result = re.search(r"\b(?:this|that|it|number|result|answer)\b", lower)
    if not asks_to_read or not refers_to_result:
        return None

    if isinstance(history, list):
        for item in reversed(history[-20:]):
            if not isinstance(item, dict) or item.get("role") != "assistant":
                continue
            content = item.get("content")
            if not isinstance(content, str):
                continue
            match = re.search(r"\bThat comes to\s+(-?\d[\d,]*(?:\.\d+)?)\b", content, re.IGNORECASE)
            if not match:
                continue
            raw_number = match.group(1)
            clean_number = raw_number.replace(",", "")
            value: int | float = float(clean_number) if "." in clean_number else int(clean_number)
            return {
                "reply": raw_number + " is " + number_to_words(value) + ".",
                "action": None,
                "source": "local",
            }

    return {
        "reply": "I don’t see a recent calculator result in this chat. Ask me to calculate it, then say “read that number.”",
        "action": None,
        "source": "local",
    }


def delete_previous_chat_turn(message: str, history: object) -> dict[str, object] | None:
    lower = message.casefold()
    if not re.search(r"\b(?:delete|remove)\b", lower) or not re.search(r"\bmessage\b", lower):
        return None
    if not re.search(r"\b(?:this|that|last|previous|my)\b", lower):
        return None

    has_previous_turn = False
    if isinstance(history, list):
        entries = history[-20:]
        last_assistant = next((index for index in range(len(entries) - 1, -1, -1)
                               if isinstance(entries[index], dict) and entries[index].get("role") == "assistant"), -1)
        if last_assistant >= 0:
            has_previous_turn = any(
                isinstance(entries[index], dict) and entries[index].get("role") == "user"
                for index in range(last_assistant - 1, -1, -1)
            )

    if not has_previous_turn:
        return {"reply": "There isn’t an earlier user message to remove yet.", "action": None, "source": "local"}
    return {
        "reply": "Removed the previous user message and J.A.R.V.I.S. reply from this chat.",
        "action": {"type": "delete_previous_turn"},
        "source": "local",
    }


def openai_reply(message: str, history: object) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return (
            "J.A.R.V.I.S. is working in local mode. I can handle time and date, arithmetic including lakh and crore, "
            "notes, timers, and trusted site links. Open-ended answers need an AI model; add your own OpenAI API key "
            "to this project's .env file and restart J.A.R.V.I.S. This is a configuration limit, not a calculator error."
        )

    safe_history: list[dict[str, str]] = []
    if isinstance(history, list):
        for item in history[-10:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                safe_history.append({"role": item["role"], "content": content[:1800]})
    safe_history.append({"role": "user", "content": message[:1800]})
    payload = {
        "model": os.environ.get("JARVIS_MODEL", "gpt-5.4-mini"),
        "instructions": (
            "You are J.A.R.V.I.S., a concise, friendly personal assistant. "
            "Be clear about uncertainty. You do not control devices, run code, browse the web, "
            "or perform actions; the local application handles its own safe commands."
        ),
        "input": safe_history,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("OpenAI rejected the API key. Check the key in .env.") from exc
        if exc.code == 429:
            try:
                error = json.loads(exc.read(8_192).decode("utf-8")).get("error", {})
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                error = {}
            error_code = error.get("code") if isinstance(error, dict) else None
            error_type = error.get("type") if isinstance(error, dict) else None
            if error_code == "credit_balance_exhausted" or error_type == "insufficient_quota":
                raise RuntimeError("OpenAI API credit balance is exhausted. Add credits in your OpenAI billing settings, then try again.") from exc
            if error_code in {"organization_spend_limit_exceeded", "project_spend_limit_exceeded"}:
                raise RuntimeError("An OpenAI API spending limit has been reached. Review the relevant organization or project limit, then try again.") from exc
            if error_code == "organization_usage_limit_exceeded":
                raise RuntimeError("Your OpenAI organization has reached its assigned API usage limit. Ask the organization owner to request an increase.") from exc
            if error_type == "rate_limit_error" or error_code in {"rate_limit_exceeded", "slow_down"}:
                raise RuntimeError("OpenAI rate limit reached. Wait a moment before retrying.") from exc
            raise RuntimeError("OpenAI returned HTTP 429. Check the API billing balance and usage limits.") from exc
        raise RuntimeError("OpenAI returned an error (HTTP " + str(exc.code) + ").") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not reach OpenAI. Check the internet connection and try again.") from exc

    text = result.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    parts: list[str] = []
    for item in result.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    if parts:
        return "\n".join(parts).strip()
    raise RuntimeError("OpenAI returned an empty response. Try again.")


def origin_is_local(origin: str | None, request_host: str = "", forwarded_proto: str = "", forwarded_host: str = "") -> bool:
    if not origin:
        return os.environ.get("JARVIS_REQUIRE_AUTH", "").strip().casefold() not in {"1", "true", "yes", "on"}
    parsed = urlparse(origin)
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == PORT:
        return True
    actual_host = (forwarded_host.strip() or request_host.strip()).casefold()
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().casefold()
    actual_scheme = forwarded_proto.split(",", 1)[0].strip().casefold() or parsed.scheme
    allowed_hosts = {host for host in (actual_host, render_host) if host}
    return parsed.netloc.casefold() in allowed_hosts and parsed.scheme == actual_scheme and actual_scheme in {"http", "https"}


class JarvisHandler(BaseHTTPRequestHandler):
    server_version = "JarvisLocal/" + APP_VERSION

    def log_message(self, format: str, *args: object) -> None:
        # Keep logs operational and omit request bodies, which may contain private chat text.
        sys.stdout.write("[JARVIS] " + (format % args) + "\n")

    def send_json(self, value: object, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def require_access(self) -> bool:
        if os.environ.get("JARVIS_REQUIRE_AUTH", "").strip().casefold() not in {"1", "true", "yes", "on"}:
            return True
        expected = os.environ.get("JARVIS_ACCESS_PASSWORD", "")
        supplied = self.headers.get("Authorization", "")
        valid = False
        if expected and supplied.startswith("Basic "):
            try:
                decoded = base64.b64decode(supplied[6:], validate=True).decode("utf-8")
                _, separator, password = decoded.partition(":")
                valid = bool(separator) and hmac.compare_digest(password, expected)
            except (ValueError, UnicodeDecodeError):
                valid = False
        if valid:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="J.A.R.V.I.S.", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False

    def read_json(self) -> dict[str, object]:
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ValueError("Invalid request size.") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("Request is too large.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Send a valid JSON request.") from exc
        if not isinstance(value, dict):
            raise ValueError("Send a JSON object.")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            ai_available = bool(os.environ.get("OPENAI_API_KEY", "").strip())
            self.send_json({
                "status": "online",
                "version": APP_VERSION,
                "mode": "openai" if ai_available else "local",
                "aiAvailable": ai_available,
                "model": os.environ.get("JARVIS_MODEL", "gpt-5.4-mini"),
                "notes": 0 if browser_notes_enabled() else len(read_notes()),
                "notesMode": "browser" if browser_notes_enabled() else "server",
                "node": {
                    "transport": "hosted" if os.environ.get("PORT") or os.environ.get("RENDER_EXTERNAL_HOSTNAME") else "loopback",
                    "port": PORT,
                    "runtime": "Python " + str(sys.version_info.major) + "." + str(sys.version_info.minor),
                    "uptimeSeconds": max(0, int(time.monotonic() - NODE_STARTED_MONOTONIC)),
                    "storage": "browser" if browser_notes_enabled() else "local file",
                },
            })
            return
        if not self.require_access():
            return
        if path == "/api/notes":
            if browser_notes_enabled():
                self.send_json({"error": "Notes are stored in this browser."}, 404)
                return
            self.send_json({"notes": read_notes()})
            return
        static_files = {
            "/": "index.html",
            "/index.html": "index.html",
            "/styles.css": "styles.css",
            "/app.js": "app.js",
            "/favicon.svg": "favicon.svg",
        }
        filename = static_files.get(path)
        if not filename:
            self.send_error(404, "Not found")
            return
        target = ROOT / filename
        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(404, "Not found")
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self.require_access():
            return
        if not origin_is_local(
            self.headers.get("Origin"),
            self.headers.get("Host", ""),
            self.headers.get("X-Forwarded-Proto", ""),
            self.headers.get("X-Forwarded-Host", ""),
        ):
            self.send_json({"error": "This assistant only accepts requests from its own page."}, 403)
            return
        path = urlparse(self.path).path
        try:
            body = self.read_json()
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
            return

        if path == "/api/chat":
            message = body.get("message")
            if not isinstance(message, str) or not message.strip():
                self.send_json({"error": "Write a message first."}, 400)
                return
            configured = bool(os.environ.get("OPENAI_API_KEY", "").strip())
            requested_mode = body.get("mode", "openai" if configured else "local")
            if not isinstance(requested_mode, str) or requested_mode not in {"local", "openai"}:
                self.send_json({"error": "Choose Local or OpenAI conversation mode."}, 400)
                return
            message = message.strip()[:1800]
            result = local_command(message)
            if result is None:
                result = delete_previous_chat_turn(message, body.get("history"))
            if result is None:
                result = read_calculation_follow_up(message, body.get("history"))
            if result is not None:
                self.send_json(result)
                return
            if requested_mode == "local":
                self.send_json({
                    "reply": (
                        "I’m in Local mode. I can handle time and date, arithmetic, notes, timers, and trusted site links. "
                        "Switch to OpenAI mode for open-ended answers."
                    ),
                    "action": None,
                    "source": "local",
                })
                return
            if not configured:
                self.send_json({"error": "OpenAI mode is unavailable until an API key is configured in the project’s .env file and the server is restarted."}, 409)
                return
            try:
                reply = openai_reply(message, body.get("history"))
                self.send_json({"reply": reply, "action": None, "source": "openai"})
            except RuntimeError as exc:
                self.send_json({"error": str(exc)}, 502)
            return

        if path == "/api/notes":
            if browser_notes_enabled():
                self.send_json({"error": "Notes are stored in this browser."}, 404)
                return
            action = body.get("action")
            if action == "add":
                text = body.get("text")
                if not isinstance(text, str):
                    self.send_json({"error": "A note needs some text."}, 400)
                    return
                try:
                    note = add_note(text)
                except (ValueError, OSError) as exc:
                    self.send_json({"error": str(exc)}, 400)
                    return
                self.send_json({"note": note}, 201)
                return
            if action == "delete":
                note_id = body.get("id")
                if not isinstance(note_id, str):
                    self.send_json({"error": "Choose a note to remove."}, 400)
                    return
                notes = read_notes()
                remaining = [item for item in notes if item["id"] != note_id]
                if len(remaining) == len(notes):
                    self.send_json({"error": "That note is no longer in Memory Vault."}, 404)
                    return
                write_notes(remaining)
                self.send_json({"notes": remaining})
                return
            self.send_json({"error": "Supported note actions are add and delete."}, 400)
            return

        self.send_json({"error": "Not found."}, 404)


def main() -> int:
    global PORT, NODE_STARTED_MONOTONIC
    load_dotenv()
    PORT = read_port()
    NODE_STARTED_MONOTONIC = time.monotonic()
    hosted = bool(os.environ.get("PORT"))
    host = "0.0.0.0" if hosted else LOCAL_HOST
    if os.environ.get("JARVIS_REQUIRE_AUTH", "").strip().casefold() in {"1", "true", "yes", "on"}:
        access_password = os.environ.get("JARVIS_ACCESS_PASSWORD", "")
        if len(access_password) < 20:
            print("JARVIS_ACCESS_PASSWORD must contain at least 20 characters when access protection is enabled.")
            return 1
    if not browser_notes_enabled():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer((host, PORT), JarvisHandler)
    except OSError as exc:
        print("Could not use " + host + ":" + str(PORT) + " (" + str(exc) + ").")
        print("If another app is using the port, set JARVIS_PORT=8766 in .env and restart.")
        return 1
    server.daemon_threads = True
    address = ("https://" + os.environ.get("RENDER_EXTERNAL_HOSTNAME", "") if hosted and os.environ.get("RENDER_EXTERNAL_HOSTNAME") else "http://" + LOCAL_HOST + ":" + str(PORT))
    print("")
    print("J.A.R.V.I.S. is ready at " + address)
    print("Mode: " + ("OpenAI chat configured" if os.environ.get("OPENAI_API_KEY", "").strip() else "local commands"))
    print("Keep this window open while you use the assistant. Press Ctrl+C to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.7, lambda: webbrowser.open(address, new=2)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\nStopping J.A.R.V.I.S. ...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


