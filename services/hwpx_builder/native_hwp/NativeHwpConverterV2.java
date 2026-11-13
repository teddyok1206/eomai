package eom.hwpx;

import java.nio.file.Path;

/** Explicit successor entrypoint. The historical V1 main remains unchanged. */
public final class NativeHwpConverterV2 {
    public static void main(String[] args) {
        try {
            if (args.length != 3) throw new IllegalArgumentException("three local files required");
            NativeHwpConverter.convertV2(Path.of(args[0]), Path.of(args[1]), Path.of(args[2]));
            System.out.println("native_hwp_conversion=CANDIDATE_CREATED profile=V2");
        } catch (Exception error) {
            System.err.println("native_hwp_conversion=FAILED error_type=" + error.getClass().getSimpleName());
            System.exit(1);
        }
    }
}
