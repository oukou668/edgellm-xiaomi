#include <android/log.h>
#include <jni.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cerrno>
#include <cstdio>
#include <deque>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include <sys/stat.h>

#include "common.h"
#include "chat.h"
#include "ggml-backend.h"
#include "llama.h"
#include "sampling.h"

#define LOG_TAG "llmbenchmark-llama"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// Decode-speed profile bucket width, in KV-cache positions. We report average decode tok/s for
// each [k*WIDTH, (k+1)*WIDTH) window so callers can see speed degrade toward 64K.
static const int DECODE_BUCKET_WIDTH = 4096;
static const size_t BACKEND_LOG_TAIL_LIMIT = 200;
static const char *SAMPLING_POLICY_VERSION = "llama_jni_safe_top_p_v1";

static llama_model *g_model = nullptr;
static llama_context *g_context = nullptr;
static llama_batch g_batch;
static bool g_batch_ready = false;
static common_chat_templates_ptr g_templates;
static int g_context_window = 0;  // total n_ctx of the live context (per-seq context * n_seq_max)
static int g_n_seq_max = 0;
static std::string g_kv_cache_type = "f16";
static int g_threads = 2;
static std::string g_accelerator_requested = "auto";
static std::string g_accelerator_active = "unknown";
static int g_n_gpu_layers = -1;
static int g_gpu_layers_offloaded = 0;
static int g_gpu_layers_offloaded_actual = -1;
static int g_model_layers = 0;
static bool g_gpu_offload_active = false;
static bool g_force_cpu = false;
static bool g_context_offload_kqv = true;
static bool g_context_op_offload = true;
static float g_raw_temperature = 0.0f;
static float g_raw_top_p = 1.0f;
static int g_raw_top_k = 0;
static float g_temperature = 0.0f;
static float g_top_p = 1.0f;
static int g_top_k = 0;
static float g_min_p = 0.0f;
static int g_min_keep = 1;
static uint32_t g_seed = 0;
static std::string g_last_error;
static std::string g_last_logits_diagnostics = "{}";
static std::string g_last_sampling_error;
static std::deque<std::string> g_backend_log_tail;
static std::mutex g_backend_log_mutex;
// Cached handle to LiveStatus.appendToken(String,String) for live UI streaming (optional).
static jclass g_live_cls = nullptr;
static jmethodID g_live_append = nullptr;

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

static std::string dev_type_name(enum ggml_backend_dev_type type) {
    switch (type) {
        case GGML_BACKEND_DEVICE_TYPE_CPU:
            return "cpu";
        case GGML_BACKEND_DEVICE_TYPE_GPU:
            return "gpu";
        case GGML_BACKEND_DEVICE_TYPE_IGPU:
            return "igpu";
        case GGML_BACKEND_DEVICE_TYPE_ACCEL:
            return "accel";
        case GGML_BACKEND_DEVICE_TYPE_META:
            return "meta";
        default:
            return "unknown";
    }
}

static bool has_gpu_device() {
    return ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_GPU) != nullptr
            || ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_IGPU) != nullptr;
}

static int gpu_device_count() {
    int count = 0;
    const size_t n = ggml_backend_dev_count();
    for (size_t i = 0; i < n; i++) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(i);
        enum ggml_backend_dev_type type = ggml_backend_dev_type(dev);
        if (type == GGML_BACKEND_DEVICE_TYPE_GPU || type == GGML_BACKEND_DEVICE_TYPE_IGPU) {
            count++;
        }
    }
    return count;
}

static void parse_gpu_offload_log(const std::string &line) {
    const size_t marker = line.find("offloaded ");
    if (marker == std::string::npos || line.find(" layers to GPU", marker) == std::string::npos) {
        return;
    }
    int actual = -1;
    int total = -1;
    if (std::sscanf(line.c_str() + marker, "offloaded %d/%d layers to GPU", &actual, &total) == 2) {
        g_gpu_layers_offloaded_actual = actual;
        g_gpu_layers_offloaded = actual;
        g_gpu_offload_active = actual > 0;
        g_model_layers = std::max(g_model_layers, total - 1);
        if (actual > 0) {
            g_accelerator_active = "vulkan";
        }
    }
}

static void append_backend_log(const char *text) {
    if (text == nullptr || text[0] == '\0') {
        return;
    }
    std::string line(text);
    while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
        line.pop_back();
    }
    parse_gpu_offload_log(line);
    std::lock_guard<std::mutex> lock(g_backend_log_mutex);
    g_backend_log_tail.push_back(line);
    while (g_backend_log_tail.size() > BACKEND_LOG_TAIL_LIMIT) {
        g_backend_log_tail.pop_front();
    }
}

static void clear_backend_log_tail() {
    std::lock_guard<std::mutex> lock(g_backend_log_mutex);
    g_backend_log_tail.clear();
}

static std::string backend_log_tail_json() {
    std::lock_guard<std::mutex> lock(g_backend_log_mutex);
    std::ostringstream out;
    out << "[";
    bool first = true;
    for (const std::string &line : g_backend_log_tail) {
        if (!first) {
            out << ",";
        }
        first = false;
        out << "\"" << json_escape(line) << "\"";
    }
    out << "]";
    return out.str();
}

static std::string backend_devices_json() {
    std::ostringstream out;
    out << "[";
    bool first = true;
    const size_t n = ggml_backend_dev_count();
    for (size_t i = 0; i < n; i++) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(i);
        if (!first) {
            out << ",";
        }
        first = false;
        ggml_backend_dev_props props {};
        ggml_backend_dev_get_props(dev, &props);
        size_t free_mem = 0;
        size_t total_mem = 0;
        ggml_backend_dev_memory(dev, &free_mem, &total_mem);
        ggml_backend_reg_t reg = ggml_backend_dev_backend_reg(dev);
        const char *name = ggml_backend_dev_name(dev);
        const char *description = ggml_backend_dev_description(dev);
        const char *reg_name = reg ? ggml_backend_reg_name(reg) : "";
        out << "{"
            << "\"index\":" << i << ","
            << "\"name\":\"" << json_escape(name == nullptr ? "" : name) << "\","
            << "\"description\":\"" << json_escape(description == nullptr ? "" : description) << "\","
            << "\"type\":\"" << dev_type_name(ggml_backend_dev_type(dev)) << "\","
            << "\"backend_reg\":\"" << json_escape(reg_name == nullptr ? "" : reg_name) << "\","
            << "\"memory_free\":" << static_cast<unsigned long long>(free_mem) << ","
            << "\"memory_total\":" << static_cast<unsigned long long>(total_mem) << ","
            << "\"props_memory_free\":" << static_cast<unsigned long long>(props.memory_free) << ","
            << "\"props_memory_total\":" << static_cast<unsigned long long>(props.memory_total)
            << "}";
    }
    out << "]";
    return out.str();
}

static std::string backend_regs_json() {
    std::ostringstream out;
    out << "[";
    bool first = true;
    const size_t n = ggml_backend_reg_count();
    for (size_t i = 0; i < n; i++) {
        ggml_backend_reg_t reg = ggml_backend_reg_get(i);
        if (!first) {
            out << ",";
        }
        first = false;
        const char *name = reg ? ggml_backend_reg_name(reg) : "";
        out << "{"
            << "\"index\":" << i << ","
            << "\"name\":\"" << json_escape(name == nullptr ? "" : name) << "\","
            << "\"device_count\":" << (reg ? ggml_backend_reg_dev_count(reg) : 0)
            << "}";
    }
    out << "]";
    return out.str();
}

static std::string gpu_diagnostics_json() {
    std::ostringstream out;
    const bool supports_gpu = llama_supports_gpu_offload();
    const int gpu_devices = gpu_device_count();
    out << "{";
    out << "\"accelerator_requested\":\"" << json_escape(g_accelerator_requested) << "\",";
    out << "\"accelerator_active\":\"" << json_escape(g_accelerator_active) << "\",";
    out << "\"gpu_layers_requested\":" << g_n_gpu_layers << ",";
    out << "\"gpu_layers_offloaded\":" << g_gpu_layers_offloaded << ",";
    out << "\"gpu_layers_offloaded_actual\":" << g_gpu_layers_offloaded_actual << ",";
    out << "\"gpu_offload_active\":" << (g_gpu_offload_active ? "true" : "false") << ",";
    out << "\"gpu_offload_proof\":\""
        << (g_gpu_layers_offloaded_actual > 0 ? "llama_cpp_offload_log" : "missing")
        << "\",";
    out << "\"llama_supports_gpu_offload\":" << (supports_gpu ? "true" : "false") << ",";
    out << "\"gpu_device_count\":" << gpu_devices << ",";
    out << "\"model_layers\":" << g_model_layers << ",";
    out << "\"context_offload_kqv\":" << (g_context_offload_kqv ? "true" : "false") << ",";
    out << "\"context_op_offload\":" << (g_context_op_offload ? "true" : "false") << ",";
    out << "\"sampling_policy_version\":\"" << SAMPLING_POLICY_VERSION << "\",";
    out << "\"sampling_raw_temperature\":" << g_raw_temperature << ",";
    out << "\"sampling_raw_top_p\":" << g_raw_top_p << ",";
    out << "\"sampling_raw_top_k\":" << g_raw_top_k << ",";
    out << "\"sampling_temperature\":" << g_temperature << ",";
    out << "\"sampling_top_p\":" << g_top_p << ",";
    out << "\"sampling_top_k\":" << g_top_k << ",";
    out << "\"sampling_min_p\":" << g_min_p << ",";
    out << "\"sampling_min_keep\":" << g_min_keep << ",";
    out << "\"last_sampling_error\":\"" << json_escape(g_last_sampling_error) << "\",";
    out << "\"last_logits_diagnostics\":" << (g_last_logits_diagnostics.empty() ? "{}" : g_last_logits_diagnostics) << ",";
    out << "\"backend_registry_count\":" << ggml_backend_reg_count() << ",";
    out << "\"backend_device_count\":" << ggml_backend_dev_count() << ",";
    out << "\"backend_regs\":" << backend_regs_json() << ",";
    out << "\"backend_devices\":" << backend_devices_json() << ",";
    out << "\"backend_log_tail\":" << backend_log_tail_json();
    out << "}";
    return out.str();
}

static void log_callback(enum ggml_log_level level, const char *text, void *) {
    int priority = ANDROID_LOG_INFO;
    if (level == GGML_LOG_LEVEL_ERROR) priority = ANDROID_LOG_ERROR;
    if (level == GGML_LOG_LEVEL_WARN) priority = ANDROID_LOG_WARN;
    if (level == GGML_LOG_LEVEL_DEBUG) priority = ANDROID_LOG_DEBUG;
    append_backend_log(text);
    __android_log_write(priority, LOG_TAG, text);
}

static void set_last_error(const std::string &message) {
    g_last_error = message;
    LOGE("%s", message.c_str());
}

// Push one freshly decoded piece to the Java LiveStatus so the UI can show generation in real
// time. No-op if the class/method weren't found at init. Runs on the worker thread (env is valid).
static void emit_token(JNIEnv *env, const std::string &item_id, const std::string &piece) {
    if (env == nullptr || g_live_cls == nullptr || g_live_append == nullptr
            || item_id.empty() || piece.empty()) {
        return;
    }
    jstring jid = env->NewStringUTF(item_id.c_str());
    jstring jpiece = env->NewStringUTF(piece.c_str());
    if (jid != nullptr && jpiece != nullptr) {
        env->CallStaticVoidMethod(g_live_cls, g_live_append, jid, jpiece);
    }
    if (jid != nullptr) {
        env->DeleteLocalRef(jid);
    }
    if (jpiece != nullptr) {
        env->DeleteLocalRef(jpiece);
    }
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

static void normalize_sampling_params(float temperature, float top_p, int top_k, uint32_t seed) {
    g_raw_temperature = temperature;
    g_raw_top_p = top_p;
    g_raw_top_k = top_k;
    g_temperature = std::isfinite(temperature) ? std::max(0.0f, temperature) : 0.0f;
    g_top_p = std::isfinite(top_p) && top_p > 0.0f ? std::min(top_p, 1.0f) : 1.0f;
    // top_k <= 0 keeps the llama.cpp CLI "disabled / use full vocab" meaning.
    g_top_k = top_k > 0 ? top_k : 0;
    g_min_p = 0.0f;
    g_min_keep = 1;
    g_seed = seed;
}

struct SampleCandidate {
    llama_token id = LLAMA_TOKEN_NULL;
    float logit = 0.0f;
    double weight = 0.0;
};

struct SampleOutcome {
    bool ok = false;
    llama_token token = LLAMA_TOKEN_NULL;
    std::string error;
    std::string diagnostics_json;
};

static std::string logits_diagnostics_json(
        const std::string &stage,
        const std::string &item_id,
        int seq_index,
        int token_position,
        int logits_index,
        int total,
        int finite_count,
        int nan_count,
        int pos_inf_count,
        int neg_inf_count,
        float min_logit,
        float max_logit,
        llama_token max_token,
        const std::string &error) {
    std::ostringstream out;
    out << "{";
    out << "\"stage\":\"" << json_escape(stage) << "\",";
    out << "\"item_id\":\"" << json_escape(item_id) << "\",";
    out << "\"seq_index\":" << seq_index << ",";
    out << "\"token_position\":" << token_position << ",";
    out << "\"logits_index\":" << logits_index << ",";
    out << "\"total_logits\":" << total << ",";
    out << "\"finite_logits\":" << finite_count << ",";
    out << "\"nan_logits\":" << nan_count << ",";
    out << "\"pos_inf_logits\":" << pos_inf_count << ",";
    out << "\"neg_inf_logits\":" << neg_inf_count << ",";
    if (finite_count > 0) {
        out << "\"min_logit\":" << min_logit << ",";
        out << "\"max_logit\":" << max_logit << ",";
        out << "\"max_token\":" << max_token << ",";
    } else {
        out << "\"min_logit\":null,\"max_logit\":null,\"max_token\":null,";
    }
    out << "\"accelerator_requested\":\"" << json_escape(g_accelerator_requested) << "\",";
    out << "\"accelerator_active\":\"" << json_escape(g_accelerator_active) << "\",";
    out << "\"gpu_layers_requested\":" << g_n_gpu_layers << ",";
    out << "\"gpu_layers_offloaded_actual\":" << g_gpu_layers_offloaded_actual << ",";
    out << "\"sampling_policy_version\":\"" << SAMPLING_POLICY_VERSION << "\",";
    out << "\"sampling_temperature\":" << g_temperature << ",";
    out << "\"sampling_top_p\":" << g_top_p << ",";
    out << "\"sampling_top_k\":" << g_top_k << ",";
    out << "\"sampling_min_p\":" << g_min_p << ",";
    out << "\"sampling_min_keep\":" << g_min_keep << ",";
    out << "\"error\":\"" << json_escape(error) << "\"";
    out << "}";
    return out.str();
}

static SampleOutcome fail_sample(
        const std::string &stage,
        const std::string &item_id,
        int seq_index,
        int token_position,
        int logits_index,
        int total,
        int finite_count,
        int nan_count,
        int pos_inf_count,
        int neg_inf_count,
        float min_logit,
        float max_logit,
        llama_token max_token,
        const std::string &reason) {
    SampleOutcome outcome;
    outcome.ok = false;
    outcome.error = "invalid_logits:" + reason;
    outcome.diagnostics_json = logits_diagnostics_json(
            stage,
            item_id,
            seq_index,
            token_position,
            logits_index,
            total,
            finite_count,
            nan_count,
            pos_inf_count,
            neg_inf_count,
            min_logit,
            max_logit,
            max_token,
            outcome.error);
    g_last_sampling_error = outcome.error;
    g_last_logits_diagnostics = outcome.diagnostics_json;
    set_last_error(outcome.error + " " + outcome.diagnostics_json);
    return outcome;
}

static SampleOutcome sample_token_checked(
        llama_context *ctx,
        int logits_index,
        std::mt19937 &rng,
        const std::string &stage,
        const std::string &item_id,
        int seq_index,
        int token_position) {
    const llama_vocab *vocab = llama_model_get_vocab(g_model);
    const int n_vocab = vocab == nullptr ? 0 : llama_vocab_n_tokens(vocab);
    const float *logits = ctx == nullptr ? nullptr : llama_get_logits_ith(ctx, logits_index);
    if (logits == nullptr || n_vocab <= 0) {
        return fail_sample(
                stage,
                item_id,
                seq_index,
                token_position,
                logits_index,
                n_vocab,
                0,
                0,
                0,
                0,
                0.0f,
                0.0f,
                LLAMA_TOKEN_NULL,
                logits == nullptr ? "missing_logits" : "empty_vocab");
    }

    std::vector<SampleCandidate> candidates;
    candidates.reserve(static_cast<size_t>(n_vocab));
    int finite_count = 0;
    int nan_count = 0;
    int pos_inf_count = 0;
    int neg_inf_count = 0;
    float min_logit = std::numeric_limits<float>::infinity();
    float max_logit = -std::numeric_limits<float>::infinity();
    llama_token max_token = LLAMA_TOKEN_NULL;

    for (llama_token token = 0; token < n_vocab; token++) {
        const float logit = logits[token];
        if (std::isfinite(logit)) {
            finite_count++;
            if (logit < min_logit) {
                min_logit = logit;
            }
            if (logit > max_logit) {
                max_logit = logit;
                max_token = token;
            }
            candidates.push_back(SampleCandidate {token, logit, 0.0});
        } else if (std::isnan(logit)) {
            nan_count++;
        } else if (logit > 0.0f) {
            pos_inf_count++;
        } else {
            neg_inf_count++;
        }
    }

    if (finite_count <= 0 || candidates.empty()) {
        return fail_sample(
                stage,
                item_id,
                seq_index,
                token_position,
                logits_index,
                n_vocab,
                finite_count,
                nan_count,
                pos_inf_count,
                neg_inf_count,
                min_logit,
                max_logit,
                max_token,
                "no_finite_logits");
    }

    SampleOutcome outcome;
    outcome.ok = true;
    outcome.diagnostics_json = logits_diagnostics_json(
            stage,
            item_id,
            seq_index,
            token_position,
            logits_index,
            n_vocab,
            finite_count,
            nan_count,
            pos_inf_count,
            neg_inf_count,
            min_logit,
            max_logit,
            max_token,
            "");
    g_last_logits_diagnostics = outcome.diagnostics_json;
    g_last_sampling_error.clear();

    if (g_temperature <= 0.0f) {
        outcome.token = max_token;
        return outcome;
    }

    if (g_top_k > 0 && static_cast<int>(candidates.size()) > g_top_k) {
        std::nth_element(
                candidates.begin(),
                candidates.begin() + g_top_k,
                candidates.end(),
                [](const SampleCandidate &a, const SampleCandidate &b) {
                    return a.logit > b.logit;
                });
        candidates.resize(static_cast<size_t>(g_top_k));
    }
    std::sort(
            candidates.begin(),
            candidates.end(),
            [](const SampleCandidate &a, const SampleCandidate &b) {
                return a.logit > b.logit;
            });

    const double inv_temp = 1.0 / static_cast<double>(g_temperature);
    const double max_scaled = static_cast<double>(candidates.front().logit) * inv_temp;
    double total_weight = 0.0;
    for (SampleCandidate &candidate : candidates) {
        candidate.weight = std::exp(static_cast<double>(candidate.logit) * inv_temp - max_scaled);
        if (!std::isfinite(candidate.weight) || candidate.weight < 0.0) {
            candidate.weight = 0.0;
        }
        total_weight += candidate.weight;
    }
    if (!std::isfinite(total_weight) || total_weight <= 0.0) {
        return fail_sample(
                stage,
                item_id,
                seq_index,
                token_position,
                logits_index,
                n_vocab,
                finite_count,
                nan_count,
                pos_inf_count,
                neg_inf_count,
                min_logit,
                max_logit,
                max_token,
                "zero_probability_mass");
    }

    size_t keep_count = candidates.size();
    double kept_weight = total_weight;
    if (g_top_p > 0.0f && g_top_p < 1.0f) {
        double cumulative = 0.0;
        keep_count = 0;
        for (size_t i = 0; i < candidates.size(); i++) {
            cumulative += candidates[i].weight;
            keep_count = i + 1;
            if (keep_count >= static_cast<size_t>(g_min_keep)
                    && cumulative / total_weight >= static_cast<double>(g_top_p)) {
                break;
            }
        }
        kept_weight = cumulative;
    }
    keep_count = std::max(keep_count, static_cast<size_t>(g_min_keep));
    keep_count = std::min(keep_count, candidates.size());
    if (keep_count == 0 || kept_weight <= 0.0 || !std::isfinite(kept_weight)) {
        return fail_sample(
                stage,
                item_id,
                seq_index,
                token_position,
                logits_index,
                n_vocab,
                finite_count,
                nan_count,
                pos_inf_count,
                neg_inf_count,
                min_logit,
                max_logit,
                max_token,
                "empty_top_p_candidates");
    }

    std::uniform_real_distribution<double> dist(0.0, kept_weight);
    const double target = dist(rng);
    double running = 0.0;
    for (size_t i = 0; i < keep_count; i++) {
        running += candidates[i].weight;
        if (running >= target) {
            outcome.token = candidates[i].id;
            return outcome;
        }
    }
    outcome.token = candidates[keep_count - 1].id;
    return outcome;
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
    if (g_force_cpu) {
        context_params.offload_kqv = false;
        context_params.op_offload = false;
    }
    g_context_offload_kqv = context_params.offload_kqv;
    g_context_op_offload = context_params.op_offload;
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
    std::string error;
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
        JNIEnv *env,
        const std::vector<std::string> &prompts,
        const std::vector<std::string> &item_ids,
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

    normalize_sampling_params(temperature, top_p, top_k, seed);

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

    std::vector<std::mt19937> rngs;
    rngs.reserve(static_cast<size_t>(n_seq));
    for (int i = 0; i < n_seq; i++) {
        rngs.emplace_back(seed + static_cast<uint32_t>(i));
    }
    std::vector<std::string> texts(n_seq);
    std::vector<int> generated(n_seq, 0);
    std::vector<int> prompt_len(n_seq, 0);
    std::vector<llama_pos> positions(n_seq, 0);
    std::vector<bool> active(n_seq, true);
    std::vector<int64_t> first_token_ms(n_seq, -1);
    std::vector<std::string> finish(n_seq, "length");
    std::vector<std::string> errors(n_seq);
    std::vector<llama_token> pending(n_seq, 0);
    std::vector<int> out_idx(n_seq, -1);
    std::vector<std::vector<int>> bucket_tokens(n_seq);
    std::vector<std::vector<int64_t>> bucket_ms(n_seq);

    // Prefill + first-token sample per sequence. Sampling each sequence's first token right after
    // its own prefill is required because the next sequence's decode invalidates prior logits.
    const int64_t prefill_start = now_ms();
    for (int i = 0; i < n_seq; i++) {
        const std::string formatted = apply_chat_template(prompts[i], thinking);
        llama_tokens tokens = common_tokenize(g_context, formatted, true, true);
        prompt_len[i] = static_cast<int>(tokens.size());
        if (tokens.empty()) {
            active[i] = false;
            finish[i] = "empty_prompt_tokens";
            errors[i] = "empty_prompt_tokens";
            continue;
        }
        if (prompt_len[i] + requested_max >= per_seq) {
            active[i] = false;
            finish[i] = "context_overflow";
            errors[i] = "context_overflow";
            continue;
        }
        const int last_idx = prefill_seq(tokens, i);
        if (last_idx < 0) {
            active[i] = false;
            finish[i] = "prompt_decode_failed";
            errors[i] = "prompt_decode_failed";
            continue;
        }
        const std::string item_id =
                i < static_cast<int>(item_ids.size()) ? item_ids[i] : std::string();
        SampleOutcome first = sample_token_checked(
                g_context, last_idx, rngs[i], "prefill", item_id, i, prompt_len[i]);
        if (!first.ok) {
            active[i] = false;
            finish[i] = "invalid_logits";
            errors[i] = first.error;
            continue;
        }
        pending[i] = first.token;
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
            emit_token(env, i < static_cast<int>(item_ids.size()) ? item_ids[i] : std::string(), piece);
            if (texts[i].find("<|im_end|>") != std::string::npos
                    || texts[i].find("</s>") != std::string::npos) {
                active[i] = false;
                finish[i] = "stop";
                continue;
            }
            if (generated[i] >= requested_max) {
                active[i] = false;
                finish[i] = "length";
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
                    errors[i] = "decode_failed";
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
            const std::string item_id =
                    i < static_cast<int>(item_ids.size()) ? item_ids[i] : std::string();
            SampleOutcome next = sample_token_checked(
                    g_context, out_idx[i], rngs[i], "decode", item_id, i, positions[i]);
            if (!next.ok) {
                active[i] = false;
                finish[i] = "invalid_logits";
                errors[i] = next.error;
                continue;
            }
            pending[i] = next.token;
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
        seq.error = errors[i];
        seq.bucket_tokens = bucket_tokens[i];
        seq.bucket_ms = bucket_ms[i];
        result.seqs.push_back(seq);
        result.total_generated += generated[i];
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
    LOGI("llama backend initialized: %s", gpu_diagnostics_json().c_str());

    // Cache the LiveStatus streaming hook (optional; generation works without it).
    jclass cls = env->FindClass("com/xiaomi/llmbenchmark/LiveStatus");
    if (cls != nullptr) {
        g_live_cls = reinterpret_cast<jclass>(env->NewGlobalRef(cls));
        g_live_append = env->GetStaticMethodID(
                g_live_cls, "appendToken", "(Ljava/lang/String;Ljava/lang/String;)V");
        env->DeleteLocalRef(cls);
    }
    if (env->ExceptionCheck()) {
        env->ExceptionClear();
        g_live_cls = nullptr;
        g_live_append = nullptr;
    }
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
        jlong seed,
        jstring accelerator,
        jint gpu_layers) {
    release_resources();
    g_threads = std::max(1, static_cast<int>(threads));
    g_temperature = static_cast<float>(temperature);
    g_top_p = static_cast<float>(top_p);
    g_top_k = static_cast<int>(top_k);
    g_seed = static_cast<uint32_t>(seed);
    normalize_sampling_params(g_temperature, g_top_p, g_top_k, g_seed);
    g_accelerator_requested = "auto";
    if (accelerator != nullptr) {
        const char *accelerator_chars = env->GetStringUTFChars(accelerator, nullptr);
        if (accelerator_chars != nullptr && std::strlen(accelerator_chars) > 0) {
            g_accelerator_requested = accelerator_chars;
        }
        if (accelerator_chars != nullptr) {
            env->ReleaseStringUTFChars(accelerator, accelerator_chars);
        }
    }
    g_force_cpu = g_accelerator_requested == "cpu";
    g_n_gpu_layers = g_force_cpu ? 0 : static_cast<int>(gpu_layers);
    g_gpu_layers_offloaded = 0;
    g_gpu_layers_offloaded_actual = -1;
    g_model_layers = 0;
    g_gpu_offload_active = false;
    g_context_offload_kqv = true;
    g_context_op_offload = true;
    g_accelerator_active = g_force_cpu ? "cpu" : "unknown";
    g_last_error.clear();
    g_last_sampling_error.clear();
    g_last_logits_diagnostics = "{}";
    clear_backend_log_tail();

    if (g_accelerator_requested == "vulkan_required"
            && (!llama_supports_gpu_offload() || !has_gpu_device())) {
        std::ostringstream error;
        error << "vulkan_required requested but no GPU/IGPU ggml device is available: "
              << gpu_diagnostics_json();
        set_last_error(error.str());
        return 20;
    }

    const char *path = env->GetStringUTFChars(model_path, nullptr);
    struct stat model_stat {};
    if (stat(path, &model_stat) != 0) {
        std::ostringstream error;
        error << "stat failed for " << path << ": " << std::strerror(errno);
        set_last_error(error.str());
        env->ReleaseStringUTFChars(model_path, path);
        return 10;
    }
    LOGI("loading GGUF: %s size=%lld threads=%d accelerator=%s gpu_layers=%d",
         path, static_cast<long long>(model_stat.st_size), g_threads,
         g_accelerator_requested.c_str(), g_n_gpu_layers);
    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = g_n_gpu_layers;
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
    g_model_layers = llama_model_n_layer(g_model);
    if (g_gpu_layers_offloaded_actual >= 0) {
        g_gpu_layers_offloaded = g_gpu_layers_offloaded_actual;
        g_gpu_offload_active = g_gpu_layers_offloaded_actual > 0;
    } else if (!g_force_cpu && llama_supports_gpu_offload() && has_gpu_device()) {
        int requested_layers = g_n_gpu_layers < 0 ? g_model_layers + 1 : g_n_gpu_layers;
        g_gpu_layers_offloaded = std::max(0, std::min(requested_layers, g_model_layers + 1));
        g_gpu_offload_active = false;
    }
    g_accelerator_active = g_gpu_offload_active ? "vulkan" : "cpu";

    if (g_accelerator_requested == "vulkan_required" && g_gpu_layers_offloaded_actual <= 0) {
        std::ostringstream error;
        error << "vulkan_required requested but no model layers were proven offloaded: "
              << gpu_diagnostics_json();
        set_last_error(error.str());
        release_resources();
        return 21;
    }

    // Load the model's official chat template(s) from GGUF metadata for prompt formatting.
    g_templates = common_chat_templates_init(g_model, "");
    if (!g_templates) {
        LOGE("common_chat_templates_init returned null; falling back to raw prompt text");
    }

    LOGI("llama model loaded successfully accelerator_active=%s gpu_layers_offloaded=%d/%d; context will be created per request",
         g_accelerator_active.c_str(), g_gpu_layers_offloaded, g_model_layers + 1);
    return 0;
}

static std::string single_result_json(const BatchResult &result) {
    if (!result.error.empty()) {
        std::ostringstream error_json;
        error_json << "{\"text\":\"\",\"finish_reason\":\"error\",\"error\":\""
                   << json_escape(result.error) << "\",\"sampling_diagnostics\":"
                   << (g_last_logits_diagnostics.empty() ? "{}" : g_last_logits_diagnostics) << "}";
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
    json << "\"error\":\"" << json_escape(seq.error) << "\",";
    json << "\"sampling_diagnostics\":" << (g_last_logits_diagnostics.empty() ? "{}" : g_last_logits_diagnostics) << ",";
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
        jlong timeout_ms,
        jstring jitem_id) {
    const char *kv_chars = env->GetStringUTFChars(jkv_cache_type, nullptr);
    std::string kv_cache_type(kv_chars);
    env->ReleaseStringUTFChars(jkv_cache_type, kv_chars);
    const char *prompt_chars = env->GetStringUTFChars(jprompt, nullptr);
    std::string prompt(prompt_chars);
    env->ReleaseStringUTFChars(jprompt, prompt_chars);

    std::vector<std::string> prompts;
    prompts.push_back(prompt);
    std::vector<std::string> item_ids;
    if (jitem_id != nullptr) {
        const char *id_chars = env->GetStringUTFChars(jitem_id, nullptr);
        item_ids.emplace_back(id_chars);
        env->ReleaseStringUTFChars(jitem_id, id_chars);
    } else {
        item_ids.emplace_back("");
    }
    BatchResult result = run_batch(
            env,
            prompts,
            item_ids,
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
        jlong timeout_ms,
        jobjectArray jitem_ids) {
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

    std::vector<std::string> item_ids;
    const jsize id_count = jitem_ids != nullptr ? env->GetArrayLength(jitem_ids) : 0;
    for (jsize i = 0; i < id_count; i++) {
        jstring element = static_cast<jstring>(env->GetObjectArrayElement(jitem_ids, i));
        if (element != nullptr) {
            const char *chars = env->GetStringUTFChars(element, nullptr);
            item_ids.emplace_back(chars);
            env->ReleaseStringUTFChars(element, chars);
            env->DeleteLocalRef(element);
        } else {
            item_ids.emplace_back("");
        }
    }

    BatchResult result = run_batch(
            env,
            prompts,
            item_ids,
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
        json << "\"error\":\"" << json_escape(seq.error) << "\",";
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
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeGpuDiagnostics(JNIEnv *env, jclass) {
    return env->NewStringUTF(gpu_diagnostics_json().c_str());
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeLastError(JNIEnv *env, jclass) {
    return env->NewStringUTF(g_last_error.c_str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_xiaomi_llmbenchmark_LlamaCppInferenceEngine_nativeUnload(JNIEnv *, jclass) {
    release_resources();
}
