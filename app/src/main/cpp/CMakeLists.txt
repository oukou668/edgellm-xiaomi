cmake_minimum_required(VERSION 3.31.6)

project(llmbenchmark-llama LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED LLAMA_CPP_DIR)
    set(LLAMA_CPP_DIR "/Users/chenhaotian/code/llama_benchmark/third_party/llama.cpp")
endif()

if(NOT EXISTS "${LLAMA_CPP_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "LLAMA_CPP_DIR does not point to llama.cpp: ${LLAMA_CPP_DIR}")
endif()

if(ANDROID_ABI STREQUAL "arm64-v8a")
    set(GGML_SYSTEM_ARCH "ARM")
    # Xiaomi 17 reports SME support, but Qwen3.5-0.8B hits a KleidiAI SME2
    # matmul SIGILL on device. Keep the Android smoke path on generic ggml CPU.
    set(GGML_CPU_KLEIDIAI OFF)
    set(GGML_OPENMP ON)
else()
    message(FATAL_ERROR "Unsupported ABI: ${ANDROID_ABI}")
endif()

add_subdirectory("${LLAMA_CPP_DIR}" build-llama)

add_library(llmbenchmark-llama SHARED llama_jni.cpp)

target_compile_definitions(llmbenchmark-llama PRIVATE
        GGML_SYSTEM_ARCH=${GGML_SYSTEM_ARCH}
        GGML_CPU_KLEIDIAI=$<BOOL:${GGML_CPU_KLEIDIAI}>
        GGML_OPENMP=$<BOOL:${GGML_OPENMP}>)

target_include_directories(llmbenchmark-llama PRIVATE
        "${LLAMA_CPP_DIR}"
        "${LLAMA_CPP_DIR}/common"
        "${LLAMA_CPP_DIR}/include"
        "${LLAMA_CPP_DIR}/ggml/include"
        "${LLAMA_CPP_DIR}/ggml/src")

target_link_libraries(llmbenchmark-llama
        llama
        llama-common
        android
        log)
