# pdf_kv_extractor

A command-line tool that extracts **key/value data** from PDF documents using the OpenAI Responses API. Point it at a PDF (or a folder of PDFs) and it writes one structured JSON file per document, with a confidence rating for every extracted field.

It works on invoices, receipts, ID cards, lab reports, forms, and scanned documents, because the model reads the PDF visually as well as textually.

## Features

- Extracts every meaningful field from all pages, including tables, headers, footers, stamps, and handwritten notes
- Uses the label printed in the document as the key (for example `Invoice No.`, `Date`, `Total`)
- Copies values exactly as printed, with no translation, guessing, or normalization
- Keeps duplicate fields instead of overwriting them (`Total`, `Total (2)`, ...)
- Rates every field `high`, `medium`, or `low` confidence
- Detects the document type (`invoice`, `ID card`, `lab report`, ...)
- Processes single files, multiple files, or whole folders (recursive by default)
- Strict structured outputs (JSON Schema) for reliable, parseable results, with a plain-JSON fallback
- Accepts custom instructions to extract extra data such as line items
- Deletes uploaded files from OpenAI after each run unless you ask it not to

## Requirements

- Python 3.9 or newer (developed on 3.11)
- An [OpenAI API key](https://platform.openai.com/api-keys)
- Python packages: `openai>=1.99.0` and `python-dotenv>=1.0.1`

## Installation

```bash
git clone https://github.com/bedevil001/pdf_kv_extractor.git
cd pdf_kv_extractor

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuration

Copy the example environment file and add your key:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1
```

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Yes | none | Your OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4.1` | Model used for extraction |

The `.env` file is read from the same folder as the script. You can also set `OPENAI_API_KEY` as a normal environment variable. `.env` is listed in `.gitignore`, so your key will not be committed.

## Usage

```bash
python pdf_kv_extractor.py <inputs...> [options]
```

`inputs` can be one or more PDF files, folders, or a mix of both.

### Examples

```bash
# Single file
python pdf_kv_extractor.py invoice.pdf

# A whole folder, saving results to ./results
python pdf_kv_extractor.py "D:\PDFs" -o results

# Ask for extra data
python pdf_kv_extractor.py invoice.pdf --instructions "Extract line items too"

# Use a high-detail render for scans and dense tables
python pdf_kv_extractor.py scan.pdf --detail high

# Load long instructions from a file
python pdf_kv_extractor.py contracts/ --instructions-file my_rules.txt
```

### Options

| Option | Description |
| --- | --- |
| `inputs` | One or more PDF files or folders (required) |
| `-o`, `--output` | Output folder (default: `output`) |
| `-m`, `--model` | Model ID (default: `OPENAI_MODEL` or `gpt-4.1`) |
| `--instructions` | Extra instructions appended to the prompt |
| `--instructions-file` | Read extra instructions from a text file (combined with `--instructions`) |
| `--plain-json` | Skip strict structured outputs and parse plain JSON instead |
| `--detail {auto,low,high}` | PDF rendering detail. Use `high` for scans and dense tables (default: `auto`) |
| `--keep-uploads` | Do not delete the uploaded files from OpenAI afterwards |
| `--no-recursive` | Do not search subfolders when an input is a folder |

## Output

Each PDF produces one JSON file named after it, for example `invoice.pdf` becomes `output/invoice.json`. If the file already exists, a numeric suffix is added (`invoice_2.json`) so nothing is overwritten.

```json
{
  "source_file": "C:\\PDFs\\invoice.pdf",
  "model": "gpt-4.1",
  "extracted_at": "2026-01-15T10:32:08.123456+00:00",
  "document_type": "invoice",
  "fields": {
    "Invoice No.": "INV-2041",
    "Date": "15/01/2026",
    "Total": "$1,250.00"
  },
  "details": [
    { "key": "Invoice No.", "value": "INV-2041", "confidence": "high" },
    { "key": "Date", "value": "15/01/2026", "confidence": "high" },
    { "key": "Total", "value": "$1,250.00", "confidence": "medium" }
  ],
  "notes": "The total is partially obscured by a stamp."
}
```

| Field | Description |
| --- | --- |
| `source_file` | Absolute path of the PDF that was processed |
| `model` | Model used for extraction |
| `extracted_at` | UTC timestamp of the extraction |
| `document_type` | Short label for the kind of document |
| `fields` | Simple `key: value` mapping. Duplicate keys become `Key (2)`, `Key (3)`, ... |
| `details` | Full list of entries, each with `key`, `value`, and `confidence` |
| `notes` | Anything unreadable, missing, or ambiguous |

Progress is printed per file, followed by a summary:

```
[1/3] invoice.pdf -> output\invoice.json (12 fields)
[2/3] receipt.pdf -> output\receipt.json (7 fields)
[3/3] scan.pdf FAILED: ...
Done: 2 extracted, 1 failed.
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All files extracted successfully |
| `1` | One or more files failed |
| `2` | Missing `OPENAI_API_KEY`, or no PDF files found |

## How it works

1. Collects the PDF files from the given inputs.
2. Uploads each PDF to OpenAI (Files API, purpose `user_data`).
3. Sends the file and an extraction prompt to the Responses API, requesting JSON that matches a strict schema.
4. Parses the response and writes the JSON result.
5. Deletes the uploaded file from OpenAI (unless `--keep-uploads` is set).

## Limitations

- **Privacy:** PDFs are uploaded to OpenAI for processing. Do not use this tool on documents you are not allowed to share with a third-party API.
- **Size:** Each PDF must be 32 MB or smaller. Larger files are skipped with an error.
- **Cost:** Every PDF is an API call, so usage is billed to your OpenAI account.
- **Accuracy:** Results come from an AI model. Check the `confidence` values and `notes`, and review important data (amounts, IDs, dates) before relying on it.
- **Not deterministic:** Running the same PDF twice may produce slightly different keys.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `error: OPENAI_API_KEY is not set` | Add the key to `.env` next to the script, or set it as an environment variable |
| `error: no PDF files found` | Check the path. Only files ending in `.pdf` are processed |
| `exceeds the 32 MB PDF limit` | Split or compress the PDF |
| JSON parse or schema errors with some models | Retry with `--plain-json` |
| Missing values on scans or dense tables | Retry with `--detail high` |

## Project structure

```
pdf_kv_extractor/
├── pdf_kv_extractor.py   # the CLI tool
├── requirements.txt      # Python dependencies
├── .env.example          # sample configuration
├── .gitignore
├── .gitattributes
├── LICENSE
└── README.md
```

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Eng-Mohamed Magdy Ali (0xBeDeViL).
