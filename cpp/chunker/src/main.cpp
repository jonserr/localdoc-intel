#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

struct Line {
    std::string_view text;
    std::size_t start_byte;
    std::size_t end_byte;
    std::uint32_t number;
};

struct Args {
    std::string input;
    std::size_t chunk_size = 1200;
    std::size_t overlap = 150;
};

Args parse_args(int argc, char* argv[]) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i];
        if (key == "--input" && i + 1 < argc) {
            args.input = argv[++i];
        } else if (key == "--chunk-size" && i + 1 < argc) {
            args.chunk_size = static_cast<std::size_t>(std::stoul(argv[++i]));
        } else if (key == "--overlap" && i + 1 < argc) {
            args.overlap = static_cast<std::size_t>(std::stoul(argv[++i]));
        } else {
            throw std::runtime_error("Unknown or incomplete argument: " + key);
        }
    }

    if (args.input.empty()) {
        throw std::runtime_error("--input is required");
    }
    if (args.chunk_size == 0) {
        throw std::runtime_error("--chunk-size must be greater than zero");
    }
    if (args.overlap >= args.chunk_size) {
        throw std::runtime_error("--overlap must be smaller than --chunk-size");
    }
    return args;
}

std::string read_file(const std::string& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        throw std::runtime_error("Could not open input file: " + path);
    }

    const std::streampos end = file.tellg();
    if (end < 0) {
        throw std::runtime_error("Could not read input file: " + path);
    }

    std::string content(static_cast<std::size_t>(end), '\0');
    file.seekg(0, std::ios::beg);
    if (!content.empty() &&
        !file.read(content.data(), static_cast<std::streamsize>(content.size()))) {
        throw std::runtime_error("Could not read input file: " + path);
    }
    return content;
}

std::vector<Line> split_lines(const std::string& content) {
    std::vector<Line> lines;
    lines.reserve(content.size() / 80 + 1);

    std::uint32_t number = 1;
    std::size_t position = 0;
    while (position < content.size()) {
        const std::size_t start = position;
        std::size_t text_end = position;
        while (
            text_end < content.size() &&
            content[text_end] != '\n' &&
            content[text_end] != '\r'
        ) {
            ++text_end;
        }

        std::size_t next = text_end;
        if (next < content.size()) {
            if (
                content[next] == '\r' &&
                next + 1 < content.size() &&
                content[next + 1] == '\n'
            ) {
                next += 2;
            } else {
                ++next;
            }
        }

        lines.push_back(
            Line{
                std::string_view(content.data() + start, text_end - start),
                start,
                text_end,
                number,
            }
        );
        position = next;
        ++number;
    }
    return lines;
}

void append_uint32_le(std::string& output, std::uint32_t value) {
    for (int shift = 0; shift < 32; shift += 8) {
        output.push_back(static_cast<char>((value >> shift) & 0xff));
    }
}

void append_uint64_le(std::string& output, std::uint64_t value) {
    for (int shift = 0; shift < 64; shift += 8) {
        output.push_back(static_cast<char>((value >> shift) & 0xff));
    }
}

void append_chunk(
    std::string& output,
    std::uint32_t index,
    std::uint32_t start_line,
    std::uint32_t end_line,
    std::uint64_t byte_start,
    std::uint64_t byte_end
) {
    append_uint32_le(output, index);
    append_uint32_le(output, start_line);
    append_uint32_le(output, end_line);
    append_uint64_le(output, byte_start);
    append_uint64_le(output, byte_end);
}

int main(int argc, char* argv[]) {
    try {
        const Args args = parse_args(argc, argv);
        const std::string content = read_file(args.input);
        const std::vector<Line> lines = split_lines(content);

        constexpr std::size_t record_size = 28;
        std::string output;
        output.reserve(
            std::max<std::size_t>(
                record_size,
                (content.size() / std::max<std::size_t>(args.chunk_size, 1) + 1) *
                    record_size
            )
        );

        if (lines.empty()) {
            append_chunk(output, 0, 0, 0, 0, 0);
        } else {
            std::uint32_t index = 0;
            std::size_t line_index = 0;
            while (line_index < lines.size()) {
                std::size_t bytes = 0;
                const std::size_t start = line_index;
                std::size_t end = line_index;

                while (
                    end < lines.size() &&
                    (bytes + lines[end].text.size() + 1 <= args.chunk_size ||
                     end == start)
                ) {
                    if (end > start) {
                        ++bytes;
                    }
                    bytes += lines[end].text.size();
                    ++end;
                }

                const Line& first = lines[start];
                const Line& last = lines[end - 1];
                append_chunk(
                    output,
                    index,
                    first.number,
                    last.number,
                    first.start_byte,
                    last.end_byte
                );

                ++index;
                if (end >= lines.size()) {
                    break;
                }

                std::size_t next = end;
                std::size_t overlap_bytes = 0;
                while (next > start && overlap_bytes < args.overlap) {
                    --next;
                    overlap_bytes += lines[next].text.size() + 1;
                }
                line_index = std::max(next, start + 1);
            }
        }

        if (
            !output.empty() &&
            std::fwrite(output.data(), 1, output.size(), stdout) != output.size()
        ) {
            throw std::runtime_error("Could not write chunk output");
        }
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "localdoc_chunker: %s\n", error.what());
        return 1;
    }
}
