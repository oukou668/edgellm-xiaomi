#include <android/log.h>
#include <jni.h>

#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <sstream>
#include <string>
#include <vector>
#include <sys/stat.h>

#include "common.h"
#include "llama.h"
#include "sampling.h"

#define LOG_TAG "llmbenchmark-llama"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static llama_model *g_model = nullptr;
static llama_context *g_context = nullptr;
static llama_batch g_batch;
static bool g_batch_ready = false;
static common_sampler *g_sampler = nullptr;
static int g_context_window = 2048;
static std::string g_kv_cache_type = "f16";
static int g_threads = 2;
static float g_temperature = 0.0f;
static float g_top_p = 1.0f;
static int g_top_k = 0;
static uint32_t g_seed = 0;
static std::string g_last_error;

static int64_t now_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

static std::string json_escape(const std::string &value) {
    std::ostringstream out;
    for (char ch : value) {
        switch (ch) {
            case '\\': out << "\\\\"; break;
            case '"': out << "\\\""; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (static_cast<unsigned char>(ch) < 0x20) {
                    out << "\\u" << std::hex << static_cast<int>(ch);
                } else {
                    out << ch;
                }
        }
    }
    return out.str();
}

static void log_callback(enum ggml_log_level level, const char *text, void *) {
    int priority = ANDROID_LOG_INFO;
    if (level == GGML_LOG_LEVEL_ERROR) priority = ANDROID_LOG_ERROR;
    if (level == GGML_LOG_LEVEL_WARN) priority = ANDROID_LOG_WARN;
    if (level == GGML_LOG_LEVEL_DEBUG) priority = ANDROID_LOG_DEBUG;
    __android_log_write(priority, LOG_TAG, text);
}

static void release_context_resources() {
    if (g_sampler != nullptr) {
        common_sampler_free(g_sampler);
        g_sampler = nullptr;
    }
    if (g_batch_ready) {
        llama_batch_free(g_batch);
        g_batch_ready = false;
    }
    if (g_context != nullptr) {
        llama_free(g_context);
        g_context = nullptr;
    }
    g_context_window = 0;
    g_kv_cache_type.clear();
}

static void release_resources() {
    release_context_resources();
    if (g_model != nullptr) {
        llama_model_free(g_model);
        g_model = nullptr;
    }
}

static void set_last_error(const std::string &message) {
    g_last_error = message;
    LOGE("%s", message.c_str());
}

static common_sampler *make_sampler() {
    common_params_sampling params;
    params.temp = g_temperature;
    params.top_p = g_top_p;
    params.top_k = g_top_k;
    params.seed = g_seed;
    return common_sampler_init(g_model, params);
}

static ggml_type kv_type_from_name(const std::string &name) {
    if (name == "q4_0") {
        return GGML_TYPE_Q4_0;
    }
    if (name == "q8_0") {
        return GGML_TYPE_Q8_0;
    }
    return GGML_TYPE_F16;
}

static int ensure_context(int context_window, const std::string &kv_cache_type) {
    const int requested_context = context_window > 0 ? context_window : 2048;
    const std::string requested_kv = kv_cache_type.empty() ? "f16" : kv_cache_type;
    if (g_context != nullptr && g_batch_ready && g_context_window == requested_context && g_kv_cache_type == requested_kv) {
        return 0;
    }
    release_context_resources();
    g_context_window = requested_context;
    g_kv_cache_type = requested_kv;

    llama_context_params context_params = llama_context_default_params();
    context_params.n_ctx = static_cast<uint32_t>(g_context_window);
    context_params.n_batch = 512;
    context_params.n_ubatch = 512;
    context_params.n_threads = g_threads;
    context_params.n_threads_batch = g_threads;
    context_params.type_k = kv_type_from_name(g_kv_cache_type);
    context_params.type_v = kv_type_from_name(g_kv_cache_type);
    LOGI("initializing llama context ctx=%d kv=%s threads=%d", g_context_window, g_kv_cache_type.c_str(), g_threads);
    g_context = llama_init_from_model(g_model, context_params);
    if (g_context == nullptr) {
        set_last_error("llama_init_from_model returned null");
        release_context_resources();
        return 2;
    }

    g_batch = llama_batch_init(g_context_window, 0, 1);
    g_batch_ready = true;
    g_sampler = make_sampler();
    if (g_sampler == nullptr) {
        set_last_error("common_sampler_init returned null");
        release_context_resources();
        return 3;
    }
    return 0;
}

static int decode_tokens(const llama_tokens &tokens, bool compute_last_logits, int64_t *latency_ms) {
    const int64_t start = now_ms();
    for (int i = 0; i < static_cast<int>(tokens.size()); i += 512) {
        const int batch_size = std::min(512, static_cast<int>(tokens.size()) - i);
        common_batch_clear(g_batch);
        for (int j = 0; j < batch_size; j++) {
            const bool logits = compute_last_logits && (i + j == static_cast<int>(tokens.size()) - 1);
            common_batch_add(g_batch, tokens[i + j], i + j, {0}, logits);
        }
        if (llama_decode(g_context, g_batch) != 0) {
            return 1;
        }
    }
    *latency_ms = now_ms() - start;
    return 0;
}

extern "C" JNIEXPORT void JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeInit(
        JNIEnv *env, jclass, jstring native_lib_dir) {
    llama_log_set(log_callback, nullptr);
    const char *path = env->GetStringUTFChars(native_lib_dir, nullptr);
    ggml_backend_load_all_from_path(path);
    LOGI("llama native init with library dir: %s", path);
    env->ReleaseStringUTFChars(native_lib_dir, path);
    llama_backend_init();
    LOGI("llama backend initialized");
}

extern "C" JNIEXPORT jint JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeLoad(
        JNIEnv *env,
        jclass,
        jstring model_path,
        jint threads,
        jdouble temperature,
        jdouble top_p,
        jint top_k,
        jlong seed) {
    release_resources();
    g_threads = std::max(1, static_cast<int>(threads));
    g_temperature = static_cast<float>(temperature);
    g_top_p = static_cast<float>(top_p);
    g_top_k = static_cast<int>(top_k);
    g_seed = static_cast<uint32_t>(seed);
    g_last_error.clear();

    const char *path = env->GetStringUTFChars(model_path, nullptr);
    struct stat model_stat {};
    if (stat(path, &model_stat) != 0) {
        std::ostringstream error;
        error << "stat failed for " << path << ": " << std::strerror(errno);
        set_last_error(error.str());
        env->ReleaseStringUTFChars(model_path, path);
        return 10;
    }
    LOGI("loading GGUF: %s size=%lld threads=%d", path, static_cast<long long>(model_stat.st_size), g_threads);
    llama_model_params model_params = llama_model_default_params();
    g_model = llama_model_load_from_file(path, model_params);
    std::string model_path_copy(path);
    env->ReleaseStringUTFChars(model_path, path);
    if (g_model == nullptr) {
        std::ostringstream error;
        error << "llama_model_load_from_file returned null for " << model_path_copy
              << " size=" << static_cast<long long>(model_stat.st_size);
        set_last_error(error.str());
        release_resources();
        return 1;
    }

    LOGI("llama model loaded successfully; context will be created per request");
    return 0;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeGenerate(
        JNIEnv *env,
        jclass,
        jstring jprompt,
        jint context_window,
        jstring jkv_cache_type,
        jint max_tokens,
        jdouble temperature,
        jdouble top_p,
        jint top_k,
        jlong seed) {
    if (g_model == nullptr) {
        return env->NewStringUTF("{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\"not_loaded\"}");
    }

    const int64_t start = now_ms();
    g_temperature = static_cast<float>(temperature);
    g_top_p = static_cast<float>(top_p);
    g_top_k = static_cast<int>(top_k);
    g_seed = static_cast<uint32_t>(seed);
    const char *kv_chars = env->GetStringUTFChars(jkv_cache_type, nullptr);
    std::string kv_cache_type(kv_chars);
    env->ReleaseStringUTFChars(jkv_cache_type, kv_chars);
    const int context_result = ensure_context(static_cast<int>(context_window), kv_cache_type);
    if (context_result != 0) {
        std::ostringstream error_json;
        error_json << "{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\"context_init_failed:"
                   << context_result << "\"}";
        return env->NewStringUTF(error_json.str().c_str());
    }
    llama_memory_clear(llama_get_memory(g_context), false);
    common_sampler_reset(g_sampler);

    const char *prompt_chars = env->GetStringUTFChars(jprompt, nullptr);
    std::string prompt(prompt_chars);
    env->ReleaseStringUTFChars(jprompt, prompt_chars);

    llama_tokens prompt_tokens = common_tokenize(g_context, prompt, true, true);
    int64_t prompt_eval_ms = 0;
    const int requested_max_tokens = std::max(1, static_cast<int>(max_tokens));
    if (prompt_tokens.empty()) {
        return env->NewStringUTF("{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\"empty_prompt_tokens\"}");
    }
    if (prompt_tokens.size() + static_cast<size_t>(requested_max_tokens) >= static_cast<size_t>(g_context_window)) {
        return env->NewStringUTF("{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\"context_overflow\"}");
    }
    if (decode_tokens(prompt_tokens, true, &prompt_eval_ms) != 0) {
        return env->NewStringUTF("{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\"prompt_decode_failed\"}");
    }

    std::string text;
    int generated_tokens = 0;
    int64_t first_token_ms = -1;
    int64_t decode_start = now_ms();
    std::string finish_reason = "length";
    llama_pos position = static_cast<llama_pos>(prompt_tokens.size());

    for (int i = 0; i < requested_max_tokens; i++) {
        llama_token token = common_sampler_sample(g_sampler, g_context, -1);
        common_sampler_accept(g_sampler, token, true);
        if (llama_vocab_is_eog(llama_model_get_vocab(g_model), token)) {
            finish_reason = "stop";
            break;
        }
        std::string piece = common_token_to_piece(g_context, token);
        if (first_token_ms < 0) {
            first_token_ms = now_ms() - start;
        }
        text += piece;
        generated_tokens++;
        common_batch_clear(g_batch);
        common_batch_add(g_batch, token, position, {0}, true);
        position++;
        if (llama_decode(g_context, g_batch) != 0) {
            finish_reason = "error";
            break;
        }
        if (text.find("<|im_end|>") != std::string::npos || text.find("</s>") != std::string::npos) {
            finish_reason = "stop";
            break;
        }
    }

    const int64_t end = now_ms();
    std::ostringstream json;
    json << "{";
    json << "\"text\":\"" << json_escape(text) << "\",";
    json << "\"prompt_tokens\":" << prompt_tokens.size() << ",";
    json << "\"generated_tokens\":" << generated_tokens << ",";
    json << "\"first_token_latency_ms\":" << first_token_ms << ",";
    json << "\"prompt_eval_latency_ms\":" << prompt_eval_ms << ",";
    json << "\"decode_latency_ms\":" << (end - decode_start) << ",";
    json << "\"total_latency_ms\":" << (end - start) << ",";
    json << "\"finish_reason\":\"" << finish_reason << "\"";
    json << "}";
    return env->NewStringUTF(json.str().c_str());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeSystemInfo(JNIEnv *env, jclass) {
    return env->NewStringUTF(llama_print_system_info());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeLastError(JNIEnv *env, jclass) {
    return env->NewStringUTF(g_last_error.c_str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeUnload(JNIEnv *, jclass) {
    release_resources();
}
