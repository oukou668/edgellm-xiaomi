package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class ModelConfig {
    static final String BACKEND_MLC = "mlc";
    static final String BACKEND_LLAMA_CPP = "llama_cpp";

    final String backendId;
    final String modelId;
    final String displayName;
    final String hfRepo;
    final String hfRevision;
    final String mlcModelUrl;
    final String modelLib;
    final String artifactFilename;
    final String artifactSha256;
    final long artifactSizeBytes;
    final String baseModelId;
    final String artifactLicense;
    final String artifactSource;
    final String quantization;
    final int contextWindow;
    final int prefillChunkSize;
    final long estimatedMemoryBytes;
    final boolean bundleWeight;
    final String smokeRole;
    final String reproductionRole;
    final String promptTemplate;
    final String minRuntimeCommit;
    final List<String> requiredFiles;
    final List<String> stopTokens;
    final GenerationParams defaultParams;

    ModelConfig(
            String backendId,
            String modelId,
            String displayName,
            String hfRepo,
            String hfRevision,
            String mlcModelUrl,
            String modelLib,
            String artifactFilename,
            String artifactSha256,
            long artifactSizeBytes,
            String baseModelId,
            String artifactLicense,
            String artifactSource,
            String quantization,
            int contextWindow,
            int prefillChunkSize,
            long estimatedMemoryBytes,
            boolean bundleWeight,
            String smokeRole,
            String reproductionRole,
            String promptTemplate,
            String minRuntimeCommit,
            List<String> requiredFiles,
            List<String> stopTokens,
            GenerationParams defaultParams) {
        this.backendId = backendId == null || backendId.isEmpty() ? BACKEND_MLC : backendId;
        this.modelId = modelId;
        this.displayName = displayName;
        this.hfRepo = hfRepo == null ? "" : hfRepo;
        this.hfRevision = hfRevision == null ? "" : hfRevision;
        this.mlcModelUrl = mlcModelUrl;
        this.modelLib = modelLib;
        this.artifactFilename = artifactFilename == null ? "" : artifactFilename;
        this.artifactSha256 = artifactSha256 == null ? "" : artifactSha256;
        this.artifactSizeBytes = artifactSizeBytes;
        this.baseModelId = baseModelId == null ? "" : baseModelId;
        this.artifactLicense = artifactLicense == null ? "" : artifactLicense;
        this.artifactSource = artifactSource == null ? "" : artifactSource;
        this.quantization = quantization;
        this.contextWindow = contextWindow;
        this.prefillChunkSize = prefillChunkSize;
        this.estimatedMemoryBytes = estimatedMemoryBytes;
        this.bundleWeight = bundleWeight;
        this.smokeRole = smokeRole == null ? "" : smokeRole;
        this.reproductionRole = reproductionRole == null ? "" : reproductionRole;
        this.promptTemplate = promptTemplate == null ? "" : promptTemplate;
        this.minRuntimeCommit = minRuntimeCommit == null ? "" : minRuntimeCommit;
        this.requiredFiles = Collections.unmodifiableList(new ArrayList<>(requiredFiles));
        this.stopTokens = Collections.unmodifiableList(new ArrayList<>(stopTokens));
        this.defaultParams = defaultParams;
    }

    static ModelConfig fromJson(JSONObject json) {
        String backendId = json.optString("backend_id");
        if (backendId.isEmpty()) {
            backendId = json.has("gguf_file") || json.has("artifact_filename") ? BACKEND_LLAMA_CPP : BACKEND_MLC;
        }
        String hfRepo = json.optString("hf_repo");
        String mlcModelUrl = json.optString("mlc_model_url");
        if (hfRepo.isEmpty() && mlcModelUrl.startsWith("HF://")) {
            hfRepo = mlcModelUrl.substring("HF://".length());
        }
        String artifactFilename = json.optString("artifact_filename", json.optString("gguf_file"));
        List<String> requiredFiles = readStringArray(json.optJSONArray("required_files"));
        List<String> stopTokens = readStringArray(json.optJSONArray("stop_tokens"));
        return new ModelConfig(
                backendId,
                json.optString("model_id"),
                json.optString("display_name", json.optString("model_id")),
                hfRepo,
                json.optString("hf_revision"),
                mlcModelUrl,
                json.optString("model_lib"),
                artifactFilename,
                json.optString("artifact_sha256", json.optString("sha256")),
                json.optLong("artifact_size_bytes", json.optLong("expected_file_size", 0L)),
                json.optString("base_model_id"),
                json.optString("artifact_license", json.optString("license")),
                json.optString("artifact_source"),
                json.optString("quantization"),
                json.optInt("context_window", json.optInt("context_window_size", 2048)),
                json.optInt("prefill_chunk_size", 128),
                json.optLong("estimated_memory_bytes", json.optLong("estimated_vram_bytes", 0L)),
                json.optBoolean("bundle_weight", false),
                json.optString("smoke_role"),
                json.optString("reproduction_role"),
                json.optString("prompt_template"),
                json.optString("min_runtime_commit", json.optString("min_llama_cpp_commit")),
                requiredFiles,
                stopTokens,
                GenerationParams.fromJson(json.optJSONObject("default_params")));
    }

    boolean isMlc() {
        return BACKEND_MLC.equals(backendId);
    }

    boolean isLlamaCpp() {
        return BACKEND_LLAMA_CPP.equals(backendId);
    }

    String artifactDisplayName() {
        return artifactFilename.isEmpty() ? modelId : artifactFilename;
    }

    @Override
    public String toString() {
        return displayName + " [" + backendId + "]";
    }

    private static List<String> readStringArray(JSONArray array) {
        List<String> values = new ArrayList<>();
        if (array != null) {
            for (int i = 0; i < array.length(); i++) {
                values.add(array.optString(i));
            }
        }
        return values;
    }
}
