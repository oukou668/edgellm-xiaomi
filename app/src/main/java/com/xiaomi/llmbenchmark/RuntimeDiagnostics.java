package com.xiaomi.llmbenchmark;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import org.json.JSONObject;

final class RuntimeDiagnostics {
    final String backendId;
    final String runtimeVersion;
    final String modelLib;
    final String nativeLibraryPath;
    final String nativeLibrarySha256;
    final String runtimeCommit;
    final Map<String, String> details;

    RuntimeDiagnostics(
            String backendId,
            String runtimeVersion,
            String modelLib,
            String nativeLibraryPath,
            String nativeLibrarySha256,
            String runtimeCommit,
            Map<String, String> details) {
        this.backendId = valueOrUnknown(backendId);
        this.runtimeVersion = valueOrUnknown(runtimeVersion);
        this.modelLib = modelLib == null ? "" : modelLib;
        this.nativeLibraryPath = nativeLibraryPath == null ? "" : nativeLibraryPath;
        this.nativeLibrarySha256 = nativeLibrarySha256 == null ? "" : nativeLibrarySha256;
        this.runtimeCommit = runtimeCommit == null ? "" : runtimeCommit;
        this.details = details == null ? Collections.emptyMap() : Collections.unmodifiableMap(new LinkedHashMap<>(details));
    }

    static RuntimeDiagnostics unknown() {
        return new RuntimeDiagnostics("unknown", "unknown", "", "", "", "", Collections.emptyMap());
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("backend_id", backendId);
        json.put("runtime_version", runtimeVersion);
        json.put("model_lib", modelLib);
        json.put("native_library_path", nativeLibraryPath);
        json.put("native_library_sha256", nativeLibrarySha256);
        json.put("runtime_commit", runtimeCommit);
        JSONObject detailJson = new JSONObject();
        for (Map.Entry<String, String> entry : details.entrySet()) {
            detailJson.put(entry.getKey(), entry.getValue());
        }
        json.put("details", detailJson);
        return json;
    }

    private static String valueOrUnknown(String value) {
        return value == null || value.isEmpty() ? "unknown" : value;
    }
}
