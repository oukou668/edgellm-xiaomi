package com.xiaomi.llmbenchmark;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

public final class ModelConfigTest {
    @Test
    public void parsesLlamaCppSchema() throws Exception {
        JSONObject json =
                new JSONObject()
                        .put("backend_id", "llama_cpp")
                        .put("model_id", "m")
                        .put("hf_repo", "repo/model")
                        .put("hf_revision", "rev")
                        .put("model_subdir", "nested-model")
                        .put("artifact_filename", "model.gguf")
                        .put("artifact_sha256", "abc")
                        .put("artifact_size_bytes", 123L)
                        .put("quantization", "Q4_K_M");
        ModelConfig model = ModelConfig.fromJson(json);
        assertTrue(model.isLlamaCpp());
        assertEquals("nested-model", model.modelSubdir);
        assertEquals("model.gguf", model.artifactFilename);
        assertEquals("abc", model.artifactSha256);
        assertEquals(123L, model.artifactSizeBytes);
    }

    @Test
    public void parsesTableReproductionFields() throws Exception {
        JSONObject json =
                new JSONObject()
                        .put("backend_id", "llama_cpp")
                        .put("model_id", "minicpm5-1b-thinking-q4")
                        .put("base_model_id", "openbmb/MiniCPM5-1B")
                        .put("hf_repo", "openbmb/MiniCPM5-1B-GGUF")
                        .put("hf_revision", "rev")
                        .put("artifact_filename", "model.gguf")
                        .put("artifact_sha256", "sha")
                        .put("artifact_size_bytes", 456L)
                        .put("artifact_license", "apache-2.0")
                        .put("artifact_source", "official_or_author_gguf")
                        .put("quantization", "Q4_K_M")
                        .put("context_window", 81920)
                        .put("reproduction_role", "table_reproduction_v1")
                        .put(
                                "default_params",
                                new JSONObject()
                                        .put("temperature", 0.9)
                                        .put("top_p", 0.95)
                                        .put("max_tokens", 4096)
                                        .put("thinking_enabled", true));
        ModelConfig model = ModelConfig.fromJson(json);
        assertEquals("openbmb/MiniCPM5-1B", model.baseModelId);
        assertEquals("apache-2.0", model.artifactLicense);
        assertEquals("official_or_author_gguf", model.artifactSource);
        assertEquals("table_reproduction_v1", model.reproductionRole);
        assertEquals(81920, model.contextWindow);
        assertTrue(model.defaultParams.thinkingEnabled);
        assertEquals(4096, model.defaultParams.maxTokens);
    }
}
