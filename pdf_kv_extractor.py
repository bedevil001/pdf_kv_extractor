import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4.1"
MAX_PDF_BYTES = 32 * 1024 * 1024

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["key", "value", "confidence"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["document_type", "fields", "notes"],
    "additionalProperties": False,
}

TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "extracted_fields",
        "schema": OUTPUT_SCHEMA,
        "strict": True,
    }
}

BASE_PROMPT = """Read the attached PDF and extract every meaningful field as key/value pairs.

Rules:
- Cover every page, including tables, headers, footers, stamps and handwritten notes.
- Use the label printed in the document as the key whenever one exists (for example "Invoice No.", "Date", "Total"). Otherwise use a short descriptive key.
- Copy values exactly as printed. Keep currency symbols, units, dates and spacing in their original form.
- Do not invent, guess, translate or normalize values. If a value is missing or unreadable, leave it empty and mention it in notes.
- If the same field appears more than once with different values, return each occurrence as a separate entry instead of overwriting.
- Mark each field confidence as "high", "medium" or "low".
- document_type: a short label such as "invoice", "ID card", "lab report".
- notes: one or two sentences about anything unreadable, missing or ambiguous."""

PLAIN_JSON_SUFFIX = """

Respond with a single valid JSON object only, with no markdown fences, using this shape:
{"document_type": "string", "fields": [{"key": "string", "value": "string", "confidence": "high|medium|low"}], "notes": "string"}"""


def build_prompt(extra_instructions, use_schema):
    prompt = BASE_PROMPT
    if extra_instructions.strip():
        prompt += "\n\nAdditional instructions:\n" + extra_instructions.strip()
    if not use_schema:
        prompt += PLAIN_JSON_SUFFIX
    return prompt


def parse_json(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


def fields_to_mapping(field_list):
    mapping = {}
    for item in field_list:
        key = str(item.get("key", "")).strip() or "unnamed"
        if key in mapping:
            base = key
            index = 2
            while f"{base} ({index})" in mapping:
                index += 1
            key = f"{base} ({index})"
        mapping[key] = str(item.get("value", ""))
    return mapping


def unique_path(path):
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def extract_pdf(client, pdf_path, model, instructions, use_schema, keep_uploads, detail):
    size = pdf_path.stat().st_size
    if size > MAX_PDF_BYTES:
        raise ValueError(f"{size / (1024 * 1024):.1f} MB exceeds the 32 MB PDF limit")

    with pdf_path.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose="user_data")

    try:
        request = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": uploaded.id, "detail": detail},
                        {"type": "input_text", "text": build_prompt(instructions, use_schema)},
                    ],
                }
            ],
        }
        if use_schema:
            request["text"] = TEXT_FORMAT

        response = client.responses.create(**request)
        return parse_json(response.output_text)
    finally:
        if not keep_uploads:
            try:
                client.files.delete(uploaded.id)
            except Exception:
                pass


def save_result(pdf_path, output_dir, model, data):
    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_dir / f"{pdf_path.stem}.json")
    field_list = data.get("fields") or []
    payload = {
        "source_file": str(pdf_path.resolve()),
        "model": model,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "document_type": str(data.get("document_type", "")),
        "fields": fields_to_mapping(field_list),
        "details": field_list,
        "notes": str(data.get("notes", "")),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def collect_pdfs(inputs, recursive):
    pdfs = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            pdfs.extend(sorted(path.glob(pattern)))
        elif path.is_file():
            if path.suffix.lower() != ".pdf":
                print(f"skip (not a PDF): {path}", file=sys.stderr)
                continue
            pdfs.append(path)
        else:
            print(f"not found: {path}", file=sys.stderr)
    return list(dict.fromkeys(pdfs))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract key/value data from PDFs with the OpenAI Responses API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pdf_kv_extractor.py invoice.pdf\n"
            "  python pdf_kv_extractor.py \"D:\\PDFs\" -o results\n"
            "  python pdf_kv_extractor.py scan.pdf --instructions \"Extract line items too\"\n\n"
            "Set OPENAI_API_KEY in the environment or in a .env file next to this script."
        ),
    )
    parser.add_argument("inputs", nargs="+", help="PDF file(s) or folder(s)")
    parser.add_argument("-o", "--output", default="output", help="output folder (default: output)")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help=f"model id (default: {DEFAULT_MODEL})")
    parser.add_argument("--instructions", default="", help="extra instructions for the model")
    parser.add_argument("--instructions-file", default="", help="read extra instructions from a text file")
    parser.add_argument("--plain-json", action="store_true", help="skip strict structured outputs")
    parser.add_argument(
        "--detail",
        choices=["auto", "low", "high"],
        default="auto",
        help="PDF rendering detail; use high for scans and dense tables (default: auto)",
    )
    parser.add_argument("--keep-uploads", action="store_true", help="do not delete uploaded files afterwards")
    parser.add_argument("--no-recursive", action="store_true", help="do not recurse into subfolders")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not os.getenv("OPENAI_API_KEY"):
        print("error: OPENAI_API_KEY is not set. Add it to .env or the environment.", file=sys.stderr)
        return 2

    instructions = args.instructions
    if args.instructions_file:
        instructions = Path(args.instructions_file).read_text(encoding="utf-8") + "\n" + instructions

    pdfs = collect_pdfs(args.inputs, recursive=not args.no_recursive)
    if not pdfs:
        print("error: no PDF files found.", file=sys.stderr)
        return 2

    client = OpenAI()
    output_dir = Path(args.output)
    failures = 0
    total = len(pdfs)

    for index, pdf_path in enumerate(pdfs, start=1):
        label = f"[{index}/{total}] {pdf_path.name}"
        try:
            data = extract_pdf(
                client,
                pdf_path,
                args.model,
                instructions,
                use_schema=not args.plain_json,
                keep_uploads=args.keep_uploads,
                detail=args.detail,
            )
            target = save_result(pdf_path, output_dir, args.model, data)
            count = len(data.get("fields") or [])
            print(f"{label} -> {target} ({count} fields)")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failures += 1
            print(f"{label} FAILED: {exc}", file=sys.stderr)

    print(f"Done: {total - failures} extracted, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
