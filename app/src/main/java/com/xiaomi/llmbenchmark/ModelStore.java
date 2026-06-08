package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;

final class ModelStore {
    private ModelStore() {}

    static File backendRoot(Context context, String backendId) {
        return new File(context.getFilesDir(), "models/" + backendId);
    }

    static File modelDirectory(Context context, ModelConfig model) {
        return new File(backendRoot(context, model.backendId), model.modelId);
    }

    static File modelArtifactFile(Context context, ModelConfig model) {
        File dir = modelDirectory(context, model);
        if (model.isLlamaCpp() && !model.artifactFilename.isEmpty()) {
            return new File(dir, model.artifactFilename);
        }
        return dir;
    }
}
