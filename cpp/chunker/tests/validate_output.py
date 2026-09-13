import struct
import subprocess
import sys
from pathlib import Path

CHUNK_RECORD = struct.Struct("<IIIQQ")


def main() -> int:
    binary = Path(sys.argv[1])
    sample_input = Path(sys.argv[2])
    result = subprocess.run(
        [
            str(binary),
            "--input",
            str(sample_input),
            "--chunk-size",
            "48",
            "--overlap",
            "0",
        ],
        check=True,
        capture_output=True,
    )

    assert result.stdout, "chunker should emit at least one binary record"
    assert len(result.stdout) % CHUNK_RECORD.size == 0
    records = list(CHUNK_RECORD.iter_unpack(result.stdout))
    source = sample_input.read_bytes()

    first = records[0]
    assert first[0] == 0
    assert first[1] == 1
    assert first[2] >= first[1]
    assert first[3] == 0
    assert first[4] > first[3]
    assert first[4] <= len(source)
    assert [record[0] for record in records] == list(range(len(records)))

    for _, _, _, byte_start, byte_end in records:
        chunk_text = (
            source[byte_start:byte_end]
            .decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        assert chunk_text
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
