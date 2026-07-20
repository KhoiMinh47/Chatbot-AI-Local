# File ingestion design

## Accepted path

The upload endpoint validates size/type, streams multipart data into a
`SpooledTemporaryFile`, uploads to MinIO, writes the document/version/job transaction and
publishes to RabbitMQ with bounded retry. The UI polls and displays upload, queue, parse,
quality, embedding and completion/error states instead of turning a transient queue problem
into a permanent opaque failure.

## Parsers and provenance

| Input | Parser behavior | Preserved location |
|---|---|---|
| PDF | Docling native-text first; local RapidOCR only below 90% page coverage | page, section, bbox |
| DOCX/HTML | Docling structure and tables | section path |
| PPTX | Docling | slide, section |
| XLSX | openpyxl read-only, formulas preserved, bounded cell batches | sheet and cell range |
| CSV | bounded row groups | row-derived section metadata |
| Source code/JSON/YAML | UTF-8, 120-line windows with 20-line overlap and symbol hint | line start/end |
| TXT/Markdown | normalized Unicode/plain text | section/order |

Parse errors have stable public codes. Empty, unsupported, corrupt and low-content files
are not silently treated as successful high-quality parses.

## Quality report and indexing

`document_parse_quality` records expected/covered units, coverage, text length, tables,
OCR units, empty units, duplicate ratio, encoding errors and warnings. Coverage below 90%,
high duplication or very low text volume produces `needs_review`.

Chunking is deterministic parent-child (parent 2000, child 256 tokens, 10% overlap), keeps
provenance boundaries and creates UUID5 IDs from version/index/type/order/text hash. Worker
embedding batches can downshift on capacity errors. Vector and lexical stores receive the
same versioned metadata.

## Operational limits

- The active README E2E completed with status `ready`, 52 chunks and about 0.904 seconds;
  it is a smoke observation, not a mixed-file benchmark.
- Docling/Torch make the worker image large and OCR remains expensive for scanned PDFs.
- Very-long-file hierarchical summaries/map-reduce and soft-delete Qdrant tombstone
  automation remain incomplete.
- Existing deleted-document points remain derived Qdrant data until a tombstone/rebuild
  workflow is added; retrieval is protected by SQL/Qdrant tenant, ACL, document-state and
  index-version filters.
- Registration email fails in local logs when Mailpit/SMTP is not running; this does not
  affect ingestion but should be fixed in the development stack.
