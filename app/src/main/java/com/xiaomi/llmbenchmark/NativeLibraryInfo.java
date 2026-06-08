package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;

final class NativeLibraryInfo {
    private NativeLibraryInfo() {}

    static File nativeLibrary(Context context, String mappedLibraryName) {
        return new File(context.getApplicationInfo().nativeLibraryDir, mappedLibraryName);
    }

    static String sha256(Context context, String mappedLibraryName) {
        try {
            File file = nativeLibrary(context, mappedLibraryName);
            return file.exists() ? Hashing.sha256(file) : "";
        } catch (Exception ignored) {
            return "";
        }
    }

    static String path(Context context, String mappedLibraryName) {
        return nativeLibrary(context, mappedLibraryName).getAbsolutePath();
    }
}

