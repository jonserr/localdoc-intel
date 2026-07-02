cmake_minimum_required(VERSION 3.16)
project(localdoc_chunker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(localdoc_chunker src/main.cpp)

enable_testing()
find_package(Python3 COMPONENTS Interpreter)

if(Python3_Interpreter_FOUND)
  add_test(
    NAME localdoc_chunker_jsonl
    COMMAND
      ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/validate_output.py
      $<TARGET_FILE:localdoc_chunker>
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/sample_input.txt
  )
endif()
