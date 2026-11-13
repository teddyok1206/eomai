package eom.hwpx;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.object.common.HWPXObject;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.Equation;
import kr.dogfoot.hwpxlib.tool.finder.ObjectFinder;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

/** The pinned SDK writer changes CRLF to CRCRLF; XML then normalizes that to LFLF.
 * Protect exact typed equation scripts before serialization, not by guessing the
 * original from already-corrupted XML. V1 and independent fingerprints stay unchanged.
 */
final class NativeHwpWriterV2 {
    private static final Pattern SCRIPT = Pattern.compile(
            "<hp:script>(EOM_NATIVE_EQ_[0-9]+)</hp:script>");

    static Map<String, String> protectScripts(List<Equation> equations) {
        var original = new HashSet<String>();
        for (Equation equation : equations) {
            if (equation.script() == null) throw new IllegalArgumentException("NATIVE_HWP_EQUATION_SCRIPT_MISSING");
            original.add(equation.script().text());
        }
        Map<String, String> replacements = new LinkedHashMap<>();
        for (Equation equation : equations) {
            String text = equation.script().text();
            if (!text.contains("\r")) continue;
            String marker = "EOM_NATIVE_EQ_" + replacements.size();
            if (original.contains(marker)) throw new IllegalArgumentException("NATIVE_HWP_EQUATION_MARKER_COLLISION");
            replacements.put(marker, text);
            equation.removeScript();
            equation.createScript();
            equation.script().addText(marker);
        }
        return replacements;
    }

    static String restoreScripts(String xml, Map<String, String> replacements, java.util.Set<String> restored) {
        Matcher matches = SCRIPT.matcher(xml);
        StringBuffer output = new StringBuffer();
        while (matches.find()) {
            String marker = matches.group(1);
            String source = replacements.get(marker);
            if (source == null) continue;
            if (!restored.add(marker)) throw new IllegalArgumentException("NATIVE_HWP_EQUATION_MARKER_DUPLICATED");
            String escaped = source.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace("\r", "&#13;");
            matches.appendReplacement(output, Matcher.quoteReplacement("<hp:script>" + escaped + "</hp:script>"));
        }
        return matches.appendTail(output).toString();
    }

    private static void equations(HWPXObject root, List<Equation> equations) throws Exception {
        for (var found : ObjectFinder.find(root, (object, parents) -> object instanceof Equation, false)) {
            equations.add((Equation) found.thisObject());
            if (equations.size() > 10000) throw new IllegalArgumentException("NATIVE_HWP_EQUATION_LIMIT");
        }
    }

    static void write(HWPXFile converted, Path candidate) throws Exception {
        List<Equation> equations = new ArrayList<>();
        for (var section : converted.sectionXMLFileList().items()) equations(section, equations);
        for (var master : converted.masterPageXMLFileList().items()) equations(master, equations);
        Map<String, String> replacements = protectScripts(equations);
        HWPXWriter.toFilepath(converted, candidate.toString());
        if (replacements.isEmpty()) return;
        Path repaired = Files.createTempFile(candidate.getParent(), ".native-equations-", ".hwpx");
        try {
            var restored = new HashSet<String>();
            try (ZipFile input = new ZipFile(candidate.toFile());
                    ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(repaired))) {
                if (input.size() > 20000) throw new IllegalArgumentException("NATIVE_HWP_ZIP_LIMIT");
                long total = 0;
                var entries = input.entries();
                while (entries.hasMoreElements()) {
                    ZipEntry entry = entries.nextElement();
                    if (entry.getSize() < 0 || entry.getSize() > 64L * 1024 * 1024
                            || (total += entry.getSize()) > 128L * 1024 * 1024) {
                        throw new IllegalArgumentException("NATIVE_HWP_ZIP_SIZE_LIMIT");
                    }
                    byte[] bytes;
                    try (var stream = input.getInputStream(entry)) { bytes = stream.readAllBytes(); }
                    if (entry.getName().matches("Contents/(section|masterpage)[0-9]+\\.xml")) {
                        bytes = restoreScripts(new String(bytes, StandardCharsets.UTF_8), replacements, restored)
                                .getBytes(StandardCharsets.UTF_8);
                    }
                    ZipEntry next = new ZipEntry(entry.getName());
                    next.setMethod(entry.getMethod());
                    next.setTime(entry.getTime());
                    if (entry.getMethod() == ZipEntry.STORED) {
                        CRC32 crc = new CRC32();
                        crc.update(bytes);
                        next.setSize(bytes.length);
                        next.setCrc(crc.getValue());
                    }
                    output.putNextEntry(next);
                    output.write(bytes);
                    output.closeEntry();
                }
            }
            if (!restored.equals(replacements.keySet())) {
                throw new IllegalArgumentException("NATIVE_HWP_EQUATION_MARKER_MISSING");
            }
            Files.move(repaired, candidate, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(repaired); }
    }
}
