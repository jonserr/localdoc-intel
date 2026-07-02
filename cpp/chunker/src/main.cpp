#include <algorithm>
#include <cstddef>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Line {
    std::string text;
    std::size_t start_byte;
    std::size_t end_byte;
    int number;
};

struct Args {
    std::string input;
    std::size_t chunk_size = 1200;
    std::size_t overlap = 150;
};

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (unsigned char c : value) {
        switch (c) {
            case '"':
                out << "\\\"";
                break;
            case '\\':
                out << "\\\\";
                break;
            case '\b':
                out << "\\b";
                break;
            case '\f':
                out << "\\f";
                break;
            case '\n':
                out << "\\n";
                break;
            case '\r':
                out << "\\r";
                break;
            case '\t':
                out << "\\t";
                break;
            default:
                if (c < 0x20) {
                    out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                        << static_cast<int>(c) << std::dec;
                } else {
                    out << c;
                }
        }
    }
    return out.str();
}

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

std::vector<Line> read_lines(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("Could not open input file: " + path);
    }

    std::ostringstream buffer;
    buffer << file.rdbuf();
    const std::string content = buffer.str();
    std::vector<Line> lines;
    int number = 1;

    std::size_t position = 0;
    while (position < content.size()) {
        const std::size_t start = position;
        std::size_t text_end = position;
        while (
            text_end < content.size() &&
            content[text_end] != '\n' &&
            content[text_end] != '\r'
        ) {
            text_end += 1;
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
                next += 1;
            }
        }

        lines.push_back(
            Line{content.substr(start, text_end - start), start, text_end, number}
        );
        position = next;
        number += 1;
    }
    return lines;
}

void write_chunk(
    std::size_t index,
    int start_line,
    int end_line,
    std::size_t byte_start,
    std::size_t byte_end,
    const std::string& text
) {
    std::cout << "{\"chunk_index\":" << index
              << ",\"start_line\":" << start_line
              << ",\"end_line\":" << end_line
              << ",\"byte_start\":" << byte_start
              << ",\"byte_end\":" << byte_end
              << ",\"text\":\"" << json_escape(text) << "\"}\n";
}

int main(int argc, char* argv[]) {
    try {
        Args args = parse_args(argc, argv);
        std::vector<Line> lines = read_lines(args.input);

        if (lines.empty()) {
            write_chunk(0, 0, 0, 0, 0, "");
            return 0;
        }

        std::size_t index = 0;
        std::size_t i = 0;
        while (i < lines.size()) {
            std::size_t bytes = 0;
            std::size_t start = i;
            std::size_t end = i;
            std::ostringstream text;

            while (
                end < lines.size() &&
                (bytes + lines[end].text.size() + 1 <= args.chunk_size || end == start)
            ) {
                if (end > start) {
                    text << '\n';
                    bytes += 1;
                }
                text << lines[end].text;
                bytes += lines[end].text.size();
                end += 1;
            }

            const Line& first = lines[start];
            const Line& last = lines[end - 1];
            write_chunk(
                index,
                first.number,
                last.number,
                first.start_byte,
                last.end_byte,
                text.str()
            );

            index += 1;
            if (end >= lines.size()) {
                break;
            }

            std::size_t next = end;
            std::size_t overlap_bytes = 0;
            while (next > start && overlap_bytes < args.overlap) {
                next -= 1;
                overlap_bytes += lines[next].text.size() + 1;
            }
            i = std::max(next, start + 1);
        }

        return 0;
    } catch (const std::exception& error) {
        std::cerr << "localdoc_chunker: " << error.what() << '\n';
        return 1;
    }
}
