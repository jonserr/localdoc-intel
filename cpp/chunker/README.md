# LocalDoc Chunker

`localdoc_chunker` is an optional internal utility for splitting UTF-8 text-like files into JSONL chunks.

It preserves:

- Chunk index.
- Start and end line.
- Start and end byte offsets.
- Source text.

Build:

```bash
make cpp-build
```

Test:

```bash
make cpp-test
```

Run:

```bash
./cpp/chunker/build/localdoc_chunker --input examples/synthetic_intake/sample.log --chunk-size 1200 --overlap 150
```

Each output line is a JSON object:

```json
{"chunk_index":0,"start_line":1,"end_line":8,"byte_start":0,"byte_end":614,"text":"..."}
```

The Django ingestion pipeline discovers the binary automatically at `cpp/chunker/build/localdoc_chunker`, `/cpp/chunker/build/localdoc_chunker`, or the path in `LOCALDOC_CHUNKER_PATH`. If the binary is missing or exits with an error, ingestion falls back to the Python chunker.
