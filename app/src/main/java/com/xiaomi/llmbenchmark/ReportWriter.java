package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

final class ReportWriter {
    private final Context context;

    ReportWriter(Context context) {
        this.context = context.getApplicationContext();
    }

    File write(BenchmarkRunReport report) throws Exception {
        String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date(report.startedAtMs));
        File dir = new File(context.getFilesDir(), "reports/" + stamp + "_" + report.benchmark.benchmarkId);
        if (!dir.exists() && !dir.mkdirs()) {
            throw new IllegalStateException("Could not create report directory: " + dir);
        }
        writeText(new File(dir, "report.json"), report.toJson().toString(2));
        writeText(new File(dir, "report.csv"), toCsv(report));
        writeText(new File(dir, "report.md"), toMarkdown(report));
        return dir;
    }

    private static String toCsv(BenchmarkRunReport report) {
        StringBuilder builder = new StringBuilder();
        builder.append(
                "id,language,category,passed,error,first_token_latency_ms,total_latency_ms,estimated_output_tokens,decode_tokens_per_second,prompt,expected_answer,output\n");
        for (BenchmarkItemResult result : report.results) {
            builder.append(csv(result.item.id)).append(',');
            builder.append(csv(result.item.language)).append(',');
            builder.append(csv(result.item.category)).append(',');
            builder.append(result.passed).append(',');
            builder.append(csv(result.error)).append(',');
            builder.append(result.firstTokenLatencyMs).append(',');
            builder.append(result.totalLatencyMs).append(',');
            builder.append(result.estimatedOutputTokens).append(',');
            builder.append(String.format(Locale.US, "%.3f", result.decodeTokensPerSecond)).append(',');
            builder.append(csv(result.item.prompt)).append(',');
            builder.append(csv(result.item.expectedAnswer)).append(',');
            builder.append(csv(result.output)).append('\n');
        }
        return builder.toString();
    }

    private static String toMarkdown(BenchmarkRunReport report) {
        StringBuilder builder = new StringBuilder();
        builder.append("# LLM Benchmark Report\n\n");
        builder.append("- Run ID: `").append(report.runId).append("`\n");
        builder.append("- Device: ").append(report.deviceInfo.summary()).append('\n');
        builder.append("- Model: ").append(report.model.displayName).append(" (`").append(report.model.modelId).append("`)\n");
        builder.append("- Benchmark: ").append(report.benchmark.displayName).append(" (`").append(report.benchmark.benchmarkId).append("`)\n");
        builder.append("- Model load: ").append(report.modelLoadMs).append(" ms\n");
        builder.append("- Passed: ").append(report.passedCount()).append('/').append(report.results.size()).append('\n');
        builder.append("- Failed items: ").append(report.failureCount()).append('\n');
        builder.append("- Avg decode tokens/s: ")
                .append(String.format(Locale.US, "%.2f", report.averageTokensPerSecond()))
                .append("\n\n");
        builder.append("| ID | Pass | First token ms | Total ms | tok/s | Output |\n");
        builder.append("| --- | --- | ---: | ---: | ---: | --- |\n");
        for (BenchmarkItemResult result : report.results) {
            builder.append("| ")
                    .append(escapeMd(result.item.id))
                    .append(" | ")
                    .append(result.passed ? "yes" : "no")
                    .append(" | ")
                    .append(result.firstTokenLatencyMs)
                    .append(" | ")
                    .append(result.totalLatencyMs)
                    .append(" | ")
                    .append(String.format(Locale.US, "%.2f", result.decodeTokensPerSecond))
                    .append(" | ")
                    .append(escapeMd(shorten(result.output.isEmpty() ? result.error : result.output, 120)))
                    .append(" |\n");
        }
        return builder.toString();
    }

    private static void writeText(File file, String text) throws Exception {
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(text.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static String csv(String value) {
        String clean = value == null ? "" : value;
        return "\"" + clean.replace("\"", "\"\"") + "\"";
    }

    private static String escapeMd(String value) {
        return (value == null ? "" : value).replace("|", "\\|").replace("\n", " ");
    }

    private static String shorten(String value, int max) {
        if (value == null || value.length() <= max) {
            return value == null ? "" : value;
        }
        return value.substring(0, max - 3) + "...";
    }
}

