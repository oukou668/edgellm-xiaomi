package com.xiaomi.llmbenchmark;

import java.io.File;
import java.util.LinkedHashMap;
import java.util.Map;

final class DummyInferenceEngine implements InferenceEngine {
    private RuntimeDiagnostics diagnostics = RuntimeDiagnostics.unknown();

    @Override
    public void load(ModelConfig model, File modelDir) {
        Map<String, String> details = new LinkedHashMap<>();
        details.put("model_path", modelDir.getAbsolutePath());
        details.put("purpose", "app_intent_report_pipeline_only");
        diagnostics =
                new RuntimeDiagnostics(
                        "dummy",
                        "DummyInferenceEngine",
                        "",
                        "",
                        "",
                        BuildConfig.APP_GIT_COMMIT,
                        details);
    }

    @Override
    public GenerationResult generate(BenchmarkItem item, GenerationParams params) {
        String text = item.expectedAnswer == null || item.expectedAnswer.isEmpty() ? "ready" : item.expectedAnswer;
        return new GenerationResult(
                text,
                1L,
                0L,
                1L,
                1L,
                Math.max(1, item.displayPrompt().split("\\s+").length),
                Math.max(1, text.split("\\s+").length),
                "dummy",
                diagnostics);
    }

    @Override
    public RuntimeDiagnostics diagnostics() {
        return diagnostics;
    }

    @Override
    public void unload() {}
}
