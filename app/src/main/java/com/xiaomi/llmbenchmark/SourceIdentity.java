package com.xiaomi.llmbenchmark;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.os.Build;
import org.json.JSONObject;

final class SourceIdentity {
    private SourceIdentity() {}

    static JSONObject collect(Context context) throws Exception {
        JSONObject json = new JSONObject();
        json.put("app_repo_path", BuildConfig.APP_REPO_PATH);
        json.put("app_git_commit", BuildConfig.APP_GIT_COMMIT);
        json.put("app_git_dirty", BuildConfig.APP_GIT_DIRTY);
        json.put("mlc_benchmark_repo_path", BuildConfig.MLC_BENCHMARK_REPO_PATH);
        json.put("mlc_benchmark_git_commit", BuildConfig.MLC_BENCHMARK_GIT_COMMIT);
        json.put("mlc_benchmark_git_dirty", BuildConfig.MLC_BENCHMARK_GIT_DIRTY);
        json.put("llama_benchmark_repo_path", BuildConfig.LLAMA_BENCHMARK_REPO_PATH);
        json.put("llama_benchmark_git_commit", BuildConfig.LLAMA_BENCHMARK_GIT_COMMIT);
        json.put("llama_benchmark_git_dirty", BuildConfig.LLAMA_BENCHMARK_GIT_DIRTY);
        json.put("llama_cpp_repo_path", BuildConfig.LLAMA_CPP_REPO_PATH);
        json.put("llama_cpp_git_commit", BuildConfig.LLAMA_CPP_GIT_COMMIT);
        json.put("llama_cpp_git_dirty", BuildConfig.LLAMA_CPP_GIT_DIRTY);
        json.put("mlc_llm_source_dir", BuildConfig.MLC_LLM_SOURCE_DIR);
        json.put("mlc_llm_git_commit", BuildConfig.MLC_LLM_GIT_COMMIT);
        json.put("mlc_llm_git_dirty", BuildConfig.MLC_LLM_GIT_DIRTY);
        json.put("android_build_fingerprint", Build.FINGERPRINT);
        json.put("device_serial", safeSerial());
        PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
        json.put("version_name", info.versionName);
        json.put("version_code", info.getLongVersionCode());
        json.put("package_name", context.getPackageName());
        json.put("apk_path", context.getPackageCodePath());
        json.put("apk_sha256", safeApkSha(context));
        return json;
    }

    private static String safeSerial() {
        try {
            return Build.getSerial();
        } catch (Exception ignored) {
            return "unavailable";
        }
    }

    private static String safeApkSha(Context context) {
        try {
            return Hashing.sha256(new java.io.File(context.getPackageCodePath()));
        } catch (Exception ignored) {
            return "";
        }
    }
}
