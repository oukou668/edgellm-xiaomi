package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import org.json.JSONArray;
import org.json.JSONObject;

final class ModelDownloader {
    private final Context context;

    ModelDownloader(Context context) {
        this.context = context.getApplicationContext();
    }

    File ensureModel(ModelConfig model, ProgressSink progress) throws Exception {
        File modelDir = new File(context.getFilesDir(), "models/" + model.modelId);
        File readyMarker = new File(modelDir, ".download-complete");
        if (readyMarker.exists()) {
            progress.onProgress("Model already downloaded: " + model.modelId);
            return modelDir;
        }
        if (!modelDir.exists() && !modelDir.mkdirs()) {
            throw new IllegalStateException("Could not create model directory: " + modelDir);
        }

        if (model.mlcModelUrl.startsWith("HF://")) {
            downloadHuggingFaceRepo(model.mlcModelUrl.substring("HF://".length()), modelDir, progress);
        } else if (model.mlcModelUrl.startsWith("https://") || model.mlcModelUrl.startsWith("http://")) {
            downloadSingleFile(model.mlcModelUrl, new File(modelDir, fileNameFromUrl(model.mlcModelUrl)), progress);
        } else {
            throw new IllegalArgumentException("Unsupported model URL: " + model.mlcModelUrl);
        }

        if (!readyMarker.createNewFile() && !readyMarker.exists()) {
            throw new IllegalStateException("Could not write model ready marker.");
        }
        return modelDir;
    }

    private void downloadHuggingFaceRepo(String repoId, File modelDir, ProgressSink progress) throws Exception {
        progress.onProgress("Listing Hugging Face repo: " + repoId);
        String apiUrl = "https://huggingface.co/api/models/" + repoId + "/tree/main?recursive=1";
        JSONArray files = new JSONArray(readUrl(apiUrl));
        int downloaded = 0;
        for (int i = 0; i < files.length(); i++) {
            JSONObject entry = files.getJSONObject(i);
            if (!"file".equals(entry.optString("type"))) {
                continue;
            }
            String path = entry.optString("path");
            if (path.isEmpty() || path.endsWith(".md") || path.startsWith(".gitattributes")) {
                continue;
            }
            File outFile = new File(modelDir, path);
            if (outFile.exists() && outFile.length() > 0) {
                continue;
            }
            String encodedPath = encodePath(path);
            String fileUrl = "https://huggingface.co/" + repoId + "/resolve/main/" + encodedPath;
            progress.onProgress("Downloading " + path);
            downloadSingleFile(fileUrl, outFile, progress);
            downloaded++;
        }
        progress.onProgress("Model files ready. New files downloaded: " + downloaded);
    }

    private static String readUrl(String value) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(value).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("User-Agent", "Xiaomi17LlmBenchmark/0.1");
        try (InputStream input = connection.getInputStream()) {
            byte[] buffer = new byte[8192];
            StringBuilder builder = new StringBuilder();
            int read;
            while ((read = input.read(buffer)) != -1) {
                builder.append(new String(buffer, 0, read));
            }
            return builder.toString();
        } finally {
            connection.disconnect();
        }
    }

    private static void downloadSingleFile(String value, File outFile, ProgressSink progress) throws Exception {
        File parent = outFile.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IllegalStateException("Could not create directory: " + parent);
        }
        File tempFile = new File(outFile.getAbsolutePath() + ".part");
        HttpURLConnection connection = (HttpURLConnection) new URL(value).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(60000);
        connection.setRequestProperty("User-Agent", "Xiaomi17LlmBenchmark/0.1");
        long total = connection.getContentLengthLong();
        try (InputStream raw = new BufferedInputStream(connection.getInputStream());
                BufferedOutputStream output = new BufferedOutputStream(new FileOutputStream(tempFile))) {
            byte[] buffer = new byte[1024 * 1024];
            long written = 0L;
            int read;
            long lastProgress = 0L;
            while ((read = raw.read(buffer)) != -1) {
                output.write(buffer, 0, read);
                written += read;
                if (written - lastProgress > 64L * 1024L * 1024L) {
                    lastProgress = written;
                    if (total > 0L) {
                        progress.onProgress(outFile.getName() + " " + (written * 100L / total) + "%");
                    }
                }
            }
        } finally {
            connection.disconnect();
        }
        if (outFile.exists() && !outFile.delete()) {
            throw new IllegalStateException("Could not replace existing file: " + outFile);
        }
        if (!tempFile.renameTo(outFile)) {
            throw new IllegalStateException("Could not finalize download: " + outFile);
        }
    }

    private static String encodePath(String path) throws Exception {
        String[] parts = path.split("/");
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < parts.length; i++) {
            if (i > 0) {
                builder.append('/');
            }
            builder.append(URLEncoder.encode(parts[i], "UTF-8").replace("+", "%20"));
        }
        return builder.toString();
    }

    private static String fileNameFromUrl(String value) {
        int index = value.lastIndexOf('/');
        return index >= 0 ? value.substring(index + 1) : "model.bin";
    }
}
