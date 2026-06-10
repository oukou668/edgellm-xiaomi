#include <android/log.h>
#include <jni.h>

#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <memory>
#include <sstream>
#include <string>
#include <vector>
#include <sys/stat.h>

#include "common.h"
#include "chat.h"
#include "llama.h"
#include "sampling.h"

#define LOG_TAG "llmbenchmark-llama"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// Decode-speed profile bucket width, in KV-cache positions. We report average decode tok/s for
// each [k*WIDTH, (k+1)*WIDTH) window so callers can see speed degrade toward 64K.
static const int DECODE_BUCKET_WIDTH = 4096;

static llama_model *g_model = nullptr;
static llama_context *g_context = nullptr;
static llama_batch g_batch;
static bool g_batch_ready = false;
static common_chat_templates_ptr g_templates;
static int g_context_window = 0;  // total n_ctx of the live context (per-seq context * n_seq_max)
static int g_n_seq_max = 0;
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

static void set_last_error(const std::string &message) {
    g_last_error = message;
    LOGE("%s", message.c_str());
}

static void release_context_resources() {
    if (g_batch_ready) {
        llama_batch_free(g_batch);
        g_batch_ready = false;
    }
    if (g_context != nullptr) {
        llama_free(g_context);
        g_context = nullptr;
    }
    g_context_window = 0;
    g_n_seq_max = 0;
    g_kv_cache_type.clear();
}

static void release_resources() {
    release_context_resources();
    g_templates.reset();
    if (g_model != nullptr) {
        llama_model_free(g_model);
        g_model = nullptr;
    }
}

static common_sampler *make_sampler_seeded(uint32_t seed) {
    common_params_sampling params;
    params.temp = g_temperature;
    params.top_p = g_top_p;
    params.top_k = g_top_k;
    params.seed = seed;
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

// Build the prompt using the model's OFFICIAL chat template (embedded in the GGUF). The thinking
// toggle is the template's own `enable_thinking` kwarg, not a hand-injected token.
static std::string apply_chat_template(const std::string &user_content, bool thinking) {
    if (!g_templates) {
        return user_content;
    }
    common_chat_templates_inputs inputs;
    common_chat_msg msg;
    msg.role = "user";
    msg.content = user_content;
    inputs.messages.push_back(msg);
    inputs.add_generation_prompt = true;
    inputs.use_jinja = true;
    inputs.enable_thinking = thinking;
    common_chat_params params = common_chat_templates_apply(g_templates.get(), inputs);
    return params.prompt;
}

// (Re)build the context for the requested per-sequence context length and batch width. The KV
// cache holds `perSeqContext * nSeq` total positions, partitioned across nSeq sequence ids, so each
// sequence gets the full per-seq budget. Holding perSeqContext at 80K with nSeq=4 therefore needs a
// ~320K-cell KV cache and may legitimately OOM on device (a stress-test result, not a bug).
static int ensure_context(int per_seq_context, const std::string &kv_cache_type, int n_seq) {
    const int per_seq = per_seq_context > 0 ? per_seq_context : 2048;
    const int total_ctx = per_seq * std::max(1, n_seq);
    const std::string requested_kv = kv_cache_type.empty() ? "f16" : kv_cache_type;
    if (g_context != nullptr && g_batch_ready && g_context_window == total_ctx
            && g_kv_cache_type == requested_kv && g_n_seq_max == n_seq) {
        return 0;
    }
    release_context_resources();
    g_context_window = total_ctx;
    g_kv_cache_type = requested_kv;
    g_n_seq_max = n_seq;

    llama_context_params context_params = llama_context_default_params();
    context_params.n_ctx = static_cast<uint32_t>(total_ctx);
    context_params.n_batch = 512;
    context_params.n_ubatch = 512;
    context_params.n_seq_max = static_cast<uint32_t>(std::max(1, n_seq));
    context_params.n_threads = g_threads;
    context_params.n_threads_batch = g_threads;
    context_params.type_k = kv_type_from_name(requested_kv);
    context_params.type_v = kv_type_from_name(requested_kv);
    LOGI("init llama context total_ctx=%d per_seq=%d n_seq=%d kv=%s threads=%d",
         total_ctx, per_seq, n_seq, requested_kv.c_str(), g_threads);
    g_context = llama_init_from_model(g_model, context_params);
    if (g_context == nullptr) {
        set_last_error("llama_init_from_model returned null");
        release_context_resources();
        return 2;
    }
    // Each token belongs to exactly one sequence, so per-token seq capacity of 1 is enough.
    g_batch = llama_batch_init(512, 0, 1);
    g_batch_ready = true;
    return 0;
}

// Decode an entire prompt into sequence `sid`, chunked at the batch width, requesting logits on the
// final token. Returns that token's batch index (for the first sample), or -1 on decode failure.
static int prefill_seq(const llama_tokens &tokens, int sid) {
    const int n = static_cast<int>(tokens.size());
    int last_idx = -1;
    for (int i = 0; i < n; i += 512) {
        const int chunk = std::min(512, n - i);
        common_batch_clear(g_batch);
        for (int j = 0; j < chunk; j++) {
            const bool is_last = (i + j == n - 1);
            common_batch_add(g_batch, tokens[i + j], i + j, {sid}, is_last);
            if (is_last) {
                last_idx = j;
            }
        }
        if (llama_decode(g_context, g_batch) != 0) {
            return -1;
        }
    }
    return last_idx;
}

static void ensure_bucket(std::vector<int> &tokens, std::vector<int64_t> &ms, int idx) {
    if (static_cast<int>(tokens.size()) <= idx) {
        tokens.resize(idx + 1, 0);
        ms.resize(idx + 1, 0);
    }
}

static std::string buckets_json(const std::vector<int> &tokens, const std::vector<int64_t> &ms) {
    std::ostringstream out;
    out << "[";
    bool first = true;
    for (size_t b = 0; b < tokens.size(); b++) {
        if (tokens[b] == 0 && ms[b] == 0) {
            continue;
        }
        if (!first) {
            out << ",";
        }
        first = false;
        const int start = static_cast<int>(b) * DECODE_BUCKET_WIDTH;
        const int end = start + DECODE_BUCKET_WIDTH;
        const double tps = ms[b] > 0 ? tokens[b] * 1000.0 / static_cast<double>(ms[b]) : 0.0;
        out << "{\"start\":" << start << ",\"end\":" << end << ",\"tokens\":" << tokens[b]
            << ",\"total_ms\":" << ms[b] << ",\"tokens_per_second\":" << tps << "}";
    }
    out << "]";
    return out.str();
}

struct SeqResult {
    std::string text;
    int prompt_tokens = 0;
    int generated_tokens = 0;
    int64_t first_token_ms = -1;
    std::string finish_reason = "length";
    std::vector<int> bucket_tokens;
    std::vector<int64_t> bucket_ms;
};

struct BatchResult {
    std::vector<SeqResult> seqs;
    int64_t prefill_ms = 0;
    int64_t decode_wall_ms = 0;
    int64_t total_ms = 0;
    int total_generated = 0;
    std::string error;  // empty on success
};

// Continuous parallel batching: prefill each prompt into its own sequence, then decode all active
// sequences together (one llama_decode per step). nSeq=1 is the ordinary single-sequence path.
static BatchResult run_batch(
        const std::vector<std::string> &prompts,
        int per_seq_context,
        const std::string &kv_cache_type,
        int max_tokens,
        float temperature,
        float top_p,
        int top_k,
        uint32_t seed,
        bool thinking,
        int64_t timeout_ms) {
    BatchResult result;
    if (g_model == nullptr) {
        result.error = "not_loaded";
        return result;
    }
    const int n_seq = static_cast<int>(prompts.size());
    if (n_seq <= 0) {
        result.error = "empty_batch";
        return result;
    }

    g_temperature = temperature;
    g_top_p = top_p;
    g_top_k = top_k;
    g_seed = seed;

    const int context_result = ensure_context(per_seq_context, kv_cache_type, n_seq);
    if (context_result != 0) {
        std::ostringstream error;
        error << "context_init_failed:" << context_result;
        result.error = error.str();
        return result;
    }

    const int per_seq = per_seq_context > 0 ? per_seq_context : 2048;
    const int requested_max = std::max(1, max_tokens);
    const int64_t start = now_ms();
    llama_memory_clear(llama_get_memory(g_context), true);

    std::vector<common_sampler *> samplers(n_seq, nullptr);
    std::vector<std::string> texts(n_seq);
    std::vector<int> generated(n_seq, 0);
    std::vector<int> prompt_len(n_seq, 0);
    std::vector<llama_pos> positions(n_seq, 0);
    std::vector<bool> active(n_seq, true);
    std::vector<int64_t> first_token_ms(n_seq, -1);
    std::vector<std::string> finish(n_seq, "length");
    std::vector<llama_token> pending(n_seq, 0);
    std::vector<int> out_idx(n_seq, -1);
    std::vector<std::vector<int>> bucket_tokens(n_seq);
    std::vector<std::vector<int64_t>> bucket_ms(n_seq);

    // Prefill + first-token sample per sequence. Sampling each sequence's first token right after
    // its own prefill is required because the next sequence's decode invalidates prior logits.
    const int64_t prefill_start = now_ms();
    for (int i = 0; i < n_seq; i++) {
        samplers[i] = make_sampler_seeded(seed + static_cast<uint32_t>(i));
        if (samplers[i] == nullptr) {
            active[i] = false;
            finish[i] = "sampler_init_failed";
            continue;
        }
        const std::string formatted = apply_chat_template(prompts[i], thinking);
        llama_tokens tokens = common_tokenize(g_context, formatted, true, true);
        prompt_len[i] = static_cast<int>(tokens.size());
        if (tokens.empty()) {
            active[i] = false;
            finish[i] = "empty_prompt_tokens";
            continue;
        }
        if (prompt_len[i] + requested_max >= per_seq) {
            active[i] = false;
            finish[i] = "context_overflow";
            continue;
        }
        const int last_idx = prefill_seq(tokens, i);
        if (last_idx < 0) {
            active[i] = false;
            finish[i] = "prompt_decode_failed";
            continue;
        }
        llama_token first = common_sampler_sample(samplers[i], g_context, last_idx);
        common_sampler_accept(samplers[i], first, true);
        pending[i] = first;
        positions[i] = prompt_len[i];
    }
    result.prefill_ms = now_ms() - prefill_start;

    const int64_t decode_start = now_ms();
    const int64_t deadline = timeout_ms > 0 ? start + timeout_ms : 0;
    bool any_active = true;
    while (any_active) {
        any_active = false;
        // 1) Process each sequence's pending token: stop conditions, then append its piece.
        for (int i = 0; i < n_seq; i++) {
            if (!active[i]) {
                continue;
            }
            if (deadline > 0 && now_ms() > deadline) {
                active[i] = false;
                finish[i] = "timeout";
                continue;
            }
            if (generated[i] >= requested_max) {
                active[i] = false;
                finish[i] = "length";
                continue;
            }
            const llama_token tok = pending[i];
            if (llama_vocab_is_eog(llama_model_get_vocab(g_model), tok)) {
                active[i] = false;
                finish[i] = "stop";
                continue;
            }
            const std::string piece = common_token_to_piece(g_context, tok);
            if (first_token_ms[i] < 0) {
                first_token_ms[i] = now_ms() - start;
            }
            texts[i] += piece;
            generated[i]++;
            if (texts[i].find("<|im_end|>") != std::string::npos
                    || texts[i].find("</s>") != std::string::npos) {
                active[i] = false;
                finish[i] = "stop";
            }
        }
        // 2) Pack one token per still-active sequence into a single batch.
        common_batch_clear(g_batch);
        int added = 0;
        for (int i = 0; i < n_seq; i++) {
            if (!active[i]) {
                continue;
            }
            common_batch_add(g_batch, pending[i], positions[i], {i}, true);
            out_idx[i] = added;
            added++;
            any_active = true;
        }
        if (added == 0) {
            break;
        }
        // 3) One decode advances every active sequence in parallel.
        const int64_t step_start = now_ms();
        if (llama_decode(g_context, g_batch) != 0) {
            for (int i = 0; i < n_seq; i++) {
                if (active[i]) {
                    active[i] = false;
                    finish[i] = "error";
                }
            }
            break;
        }
        const int64_t step_ms = now_ms() - step_start;
        // 4) Attribute this step to each sequence's KV-length bucket and sample its next token.
        for (int i = 0; i < n_seq; i++) {
            if (!active[i]) {
                continue;
            }
            const int bucket = positions[i] / DECODE_BUCKET_WIDTH;
            ensure_bucket(bucket_tokens[i], bucket_ms[i], bucket);
            bucket_tokens[i][bucket] += 1;
            bucket_ms[i][bucket] += step_ms;
            llama_token next = common_sampler_sample(samplers[i], g_context, out_idx[i]);
            common_sampler_accept(samplers[i], next, true);
            pending[i] = next;
            positions[i] += 1;
        }
    }
    result.decode_wall_ms = now_ms() - decode_start;

    for (int i = 0; i < n_seq; i++) {
        SeqResult seq;
        seq.text = texts[i];
        seq.prompt_tokens = prompt_len[i];
        seq.generated_tokens = generated[i];
        seq.first_token_ms = first_token_ms[i];
        seq.finish_reason = finish[i];
        seq.bucket_tokens = bucket_tokens[i];
        seq.bucket_ms = bucket_ms[i];
        result.seqs.push_back(seq);
        result.total_generated += generated[i];
        if (samplers[i] != nullptr) {
            common_sampler_free(samplers[i]);
        }
    }
    result.total_ms = now_ms() - start;
    return result;
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

    // Load the model's official chat template(s) from GGUF metadata for prompt formatting.
    g_templates = common_chat_templates_init(g_model, "");
    if (!g_templates) {
        LOGE("common_chat_templates_init returned null; falling back to raw prompt text");
    }

    LOGI("llama model loaded successfully; context will be created per request");
    return 0;
}

static std::string single_result_json(const BatchResult &result) {
    if (!result.error.empty()) {
        std::ostringstream error_json;
        error_json << "{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\""
                   << json_escape(result.error) << "\"}";
        return error_json.str();
    }
    const SeqResult &seq = result.seqs.front();
    std::ostringstream json;
    json << "{";
    json << "\"text\":\"" << json_escape(seq.text) << "\",";
    json << "\"prompt_tokens\":" << seq.prompt_tokens << ",";
    json << "\"generated_tokens\":" << seq.generated_tokens << ",";
    json << "\"first_token_latency_ms\":" << seq.first_token_ms << ",";
    json << "\"prompt_eval_latency_ms\":" << result.prefill_ms << ",";
    json << "\"decode_latency_ms\":" << result.decode_wall_ms << ",";
    json << "\"total_latency_ms\":" << result.total_ms << ",";
    json << "\"finish_reason\":\"" << json_escape(seq.finish_reason) << "\",";
    json << "\"decode_speed_buckets\":" << buckets_json(seq.bucket_tokens, seq.bucket_ms);
    json << "}";
    return json.str();
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
        jlong seed,
        jboolean thinking,
        jlong timeout_ms) {
    const char *kv_chars = env->GetStringUTFChars(jkv_cache_type, nullptr);
    std::string kv_cache_type(kv_chars);
    env->ReleaseStringUTFChars(jkv_cache_type, kv_chars);
    const char *prompt_chars = env->GetStringUTFChars(jprompt, nullptr);
    std::string prompt(prompt_chars);
    env->ReleaseStringUTFChars(jprompt, prompt_chars);

    std::vector<std::string> prompts;
    prompts.push_back(prompt);
    BatchResult result = run_batch(
            prompts,
            static_cast<int>(context_window),
            kv_cache_type,
            static_cast<int>(max_tokens),
            static_cast<float>(temperature),
            static_cast<float>(top_p),
            static_cast<int>(top_k),
            static_cast<uint32_t>(seed),
            thinking == JNI_TRUE,
            static_cast<int64_t>(timeout_ms));
    return env->NewStringUTF(single_result_json(result).c_str());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeGenerateBatch(
        JNIEnv *env,
        jclass,
        jobjectArray jprompts,
        jint per_seq_context,
        jstring jkv_cache_type,
        jint max_tokens,
        jdouble temperature,
        jdouble top_p,
        jint top_k,
        jlong seed,
        jboolean thinking,
        jlong timeout_ms) {
    const char *kv_chars = env->GetStringUTFChars(jkv_cache_type, nullptr);
    std::string kv_cache_type(kv_chars);
    env->ReleaseStringUTFChars(jkv_cache_type, kv_chars);

    std::vector<std::string> prompts;
    const jsize n = env->GetArrayLength(jprompts);
    for (jsize i = 0; i < n; i++) {
        jstring element = static_cast<jstring>(env->GetObjectArrayElement(jprompts, i));
        const char *chars = env->GetStringUTFChars(element, nullptr);
        prompts.emplace_back(chars);
        env->ReleaseStringUTFChars(element, chars);
        env->DeleteLocalRef(element);
    }

    BatchResult result = run_batch(
            prompts,
            static_cast<int>(per_seq_context),
            kv_cache_type,
            static_cast<int>(max_tokens),
            static_cast<float>(temperature),
            static_cast<float>(top_p),
            static_cast<int>(top_k),
            static_cast<uint32_t>(seed),
            thinking == JNI_TRUE,
            static_cast<int64_t>(timeout_ms));

    std::ostringstream json;
    json << "{";
    json << "\"batch_size\":" << static_cast<int>(n) << ",";
    if (!result.error.empty()) {
        json << "\"error\":\"" << json_escape(result.error) << "\",";
    }
    json << "\"aggregate_prefill_latency_ms\":" << result.prefill_ms << ",";
    json << "\"aggregate_decode_latency_ms\":" << result.decode_wall_ms << ",";
    json << "\"total_generated_tokens\":" << result.total_generated << ",";
    const double agg_tps = result.decode_wall_ms > 0
            ? result.total_generated * 1000.0 / static_cast<double>(result.decode_wall_ms)
            : 0.0;
    json << "\"aggregate_tokens_per_second\":" << agg_tps << ",";
    json << "\"sequences\":[";
    for (size_t i = 0; i < result.seqs.size(); i++) {
        const SeqResult &seq = result.seqs[i];
        if (i > 0) {
            json << ",";
        }
        json << "{";
        json << "\"text\":\"" << json_escape(seq.text) << "\",";
        json << "\"prompt_tokens\":" << seq.prompt_tokens << ",";
        json << "\"generated_tokens\":" << seq.generated_tokens << ",";
        json << "\"first_token_latency_ms\":" << seq.first_token_ms << ",";
        json << "\"decode_latency_ms\":" << result.decode_wall_ms << ",";
        json << "\"finish_reason\":\"" << json_escape(seq.finish_reason) << "\",";
        json << "\"decode_speed_buckets\":" << buckets_json(seq.bucket_tokens, seq.bucket_ms);
        json << "}";
    }
    json << "]}";
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
