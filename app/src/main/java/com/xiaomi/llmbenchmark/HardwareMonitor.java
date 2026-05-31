package com.xiaomi.llmbenchmark;

import android.app.ActivityManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Debug;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

final class HardwareMonitor implements AutoCloseable {
    private static final double MIN_REASONABLE_TEMP_C = -40.0;
    private static final double MAX_REASONABLE_TEMP_C = 150.0;

    private final Context context;
    private final long startMs;
    private final long intervalMs;
    private final List<HardwareSample> samples = Collections.synchronizedList(new ArrayList<>());
    private volatile boolean running = true;
    private volatile String phase = "idle";
    private volatile String itemId = "";
    private Thread worker;

    HardwareMonitor(Context context, long intervalMs) {
        this.context = context.getApplicationContext();
        this.startMs = System.currentTimeMillis();
        this.intervalMs = Math.max(250L, intervalMs);
    }

    void start() {
        sampleNow();
        worker =
                new Thread(
                        () -> {
                            while (running) {
                                sleep(intervalMs);
                                sampleNow();
                            }
                        },
                        "hardware-monitor");
        worker.setDaemon(true);
        worker.start();
    }

    void setPhase(String phase, String itemId) {
        this.phase = phase == null ? "" : phase;
        this.itemId = itemId == null ? "" : itemId;
        sampleNow();
    }

    List<HardwareSample> snapshot() {
        synchronized (samples) {
            return new ArrayList<>(samples);
        }
    }

    HardwareSummary summary() {
        return new HardwareSummary(snapshot());
    }

    @Override
    public void close() {
        running = false;
        if (worker != null) {
            try {
                worker.join(1000L);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }
        sampleNow();
    }

    private void sampleNow() {
        try {
            ActivityManager.MemoryInfo memoryInfo = new ActivityManager.MemoryInfo();
            ActivityManager activityManager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (activityManager != null) {
                activityManager.getMemoryInfo(memoryInfo);
            }

            Debug.MemoryInfo debugMemory = new Debug.MemoryInfo();
            Debug.getMemoryInfo(debugMemory);

            ThermalReading thermal = readMaxThermal();
            samples.add(
                    new HardwareSample(
                            System.currentTimeMillis() - startMs,
                            phase,
                            itemId,
                            memoryInfo.availMem,
                            memoryInfo.totalMem,
                            debugMemory.getTotalPss() * 1024L,
                            Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory(),
                            Debug.getNativeHeapAllocatedSize(),
                            readBatteryTemperatureC(),
                            thermal.temperatureC,
                            thermal.zone));
        } catch (Exception ignored) {
        }
    }

    private double readBatteryTemperatureC() {
        try {
            Intent intent = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (intent == null) {
                return Double.NaN;
            }
            int tempTenthsC = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
            return tempTenthsC == Integer.MIN_VALUE ? Double.NaN : tempTenthsC / 10.0;
        } catch (Exception ignored) {
            return Double.NaN;
        }
    }

    private static ThermalReading readMaxThermal() {
        File root = new File("/sys/class/thermal");
        File[] zones = root.listFiles((dir, name) -> name.startsWith("thermal_zone"));
        if (zones == null) {
            return new ThermalReading(Double.NaN, "");
        }
        double maxTemp = Double.NaN;
        String maxZone = "";
        for (File zone : zones) {
            Double temp = readThermalZoneTemp(zone);
            if (temp == null) {
                continue;
            }
            String type = readOneLine(new File(zone, "type"));
            String name = type.isEmpty() ? zone.getName() : type;
            if (isIgnoredThermalZone(name)) {
                continue;
            }
            if (Double.isNaN(maxTemp) || temp > maxTemp) {
                maxTemp = temp;
                maxZone = name;
            }
        }
        return new ThermalReading(maxTemp, maxZone);
    }

    private static Double readThermalZoneTemp(File zone) {
        String value = readOneLine(new File(zone, "temp"));
        if (value.isEmpty()) {
            return null;
        }
        try {
            double raw = Double.parseDouble(value.trim());
            double temperatureC = raw > 1000.0 ? raw / 1000.0 : raw;
            if (temperatureC < MIN_REASONABLE_TEMP_C || temperatureC > MAX_REASONABLE_TEMP_C) {
                return null;
            }
            return temperatureC;
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static boolean isIgnoredThermalZone(String name) {
        String lower = name == null ? "" : name.toLowerCase(Locale.US);
        return lower.contains("ibat")
                || lower.contains("vbat")
                || lower.contains("bcl")
                || lower.contains("trip");
    }

    private static String readOneLine(File file) {
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line = reader.readLine();
            return line == null ? "" : line.trim();
        } catch (Exception ignored) {
            return "";
        }
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    private static final class ThermalReading {
        final double temperatureC;
        final String zone;

        ThermalReading(double temperatureC, String zone) {
            this.temperatureC = temperatureC;
            this.zone = zone == null ? "" : zone.toLowerCase(Locale.US);
        }
    }
}
