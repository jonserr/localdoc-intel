cmake_minimum_required(VERSION 3.16)
project(localdoc_chunker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Single-config generators default to an unoptimized build; the benchmark
# numbers assume Release.
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

add_executable(localdoc_chunker src/main.cpp)
target_compile_options(localdoc_chunker PRIVATE -Wall -Wextra -Wpedantic)

enable_testing()
find_package(Python3 COMPONENTS Interpreter)

if(Python3_Interpreter_FOUND)
  add_test(
    NAME localdoc_chunker_binary_records
    COMMAND
      ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/validate_output.py
      $<TARGET_FILE:localdoc_chunker>
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/sample_input.txt
  )
endif()
