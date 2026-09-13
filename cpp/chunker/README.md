# LocalDoc Chunker

`localdoc_chunker` is an optional internal utility for finding chunk boundaries
in large UTF-8 text-like files.

It preserves:

- Chunk index.
- Start and end line.
- Start and end byte offsets.
- Compact little-endian output (28 bytes per chunk).

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
./cpp/chunker/build/localdoc_chunker \
  --input examples/synthetic_intake/sample.log \
  --chunk-size 1200 \
  --overlap 150 > chunks.bin
```

Each output record has the Python `struct` format `<IIIQQ`:

```python
record = struct.Struct("<IIIQQ")
for chunk_index, start_line, end_line, byte_start, byte_end in record.iter_unpack(data):
    ...
```

The binary emits offsets rather than copying source text into its output. Django
uses those offsets to slice the source bytes already held by ingestion, normalize
CRLF/CR separators to LF, and calculate the existing whitespace token count.

The Django ingestion pipeline discovers the binary automatically at
`cpp/chunker/build/localdoc_chunker`, `/cpp/chunker/build/localdoc_chunker`,
or the path in `LOCALDOC_CHUNKER_PATH`. It is used only for eligible text/code
files strictly larger than 4 MiB, as documented in the root README. If the
binary is missing, times out, exits with an error, or emits malformed records,
ingestion falls back to the Python chunker.

## Historical performance measurements

These measurements were recorded during 1.1.0 development. They were not rerun for the release checks, and timings vary with hardware and machine load.

Environment: Apple M5, macOS 27.0, Python 3.14.6, Apple clang 21.0.0, `-O2 -std=c++17`, chunk size 1200, and overlap 150. Each timing is the median of five runs, or of three runs at 128 MiB.

| Input | Python | C++ pipeline | Python / C++ |
|---|---:|---:|---:|
| 64 KiB, LF | 0.68 ms | 2.91 ms | 0.24× |
| 4 MiB, LF | 48.11 ms | 26.54 ms | 1.81× |
| 32 MiB, LF | 411.43 ms | 204.87 ms | 2.01× |
| 128 MiB, LF | 1810.36 ms | 795.75 ms | 2.28× |

Fields matched and byte offsets round-tripped for the recorded LF, CRLF, and Unicode cases.

The measurement covers the chunker pipeline only. It excludes parsing, OCR, database writes, embeddings, and vector indexing. Small files are the worst case, because the process spawn costs about 2 ms and the Python path never pays it. The production cutoff stays strictly greater than 4 MiB for that reason.

Reproduce the full set with:

```bash
make cpp-build && python scripts/benchmark_chunker.py --sizes 0.0625,0.5,1,4,32 --runs 5
```
