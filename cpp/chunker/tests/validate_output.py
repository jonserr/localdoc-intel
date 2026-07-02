import json
import subprocess
import sys
from pathlib import Path


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
        text=True,
    )

    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert rows, "chunker should emit at least one JSONL row"
    assert rows[0]["chunk_index"] == 0
    assert rows[0]["start_line"] == 1
    assert rows[0]["end_line"] >= rows[0]["start_line"]
    assert rows[0]["byte_start"] == 0
    assert rows[0]["byte_end"] > rows[0]["byte_start"]
    assert isinstance(rows[0]["text"], str)
    assert [row["chunk_index"] for row in rows] == list(range(len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
