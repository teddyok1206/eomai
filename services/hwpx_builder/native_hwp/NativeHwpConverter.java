package eom.hwpx;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import kr.dogfoot.hwp2hwpx.Hwp2Hwpx;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.control.*;
import kr.dogfoot.hwplib.object.bodytext.control.gso.*;
import kr.dogfoot.hwplib.object.bodytext.control.gso.caption.Caption;
import kr.dogfoot.hwplib.object.bodytext.control.gso.textbox.TextBox;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.object.docinfo.bindata.BinDataType;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

/** File-only adapter. No network, NAS, credentials, orchestration or publication. */
public final class NativeHwpConverter {
    private final List<String> paragraphs = new ArrayList<>();
    private final List<String> tables = new ArrayList<>();
    private final List<String> equations = new ArrayList<>();
    private final Map<String, Integer> shapes = new LinkedHashMap<>();

    private NativeHwpConverter() {
        for (String name : List.of("pic", "container", "rect", "ellipse", "arc",
                "polygon", "curve", "line", "connectLine")) shapes.put(name, 0);
    }

    private static String digest(byte[] data) throws Exception {
        return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
    }

    private static String fileDigest(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var input = Files.newInputStream(path)) {
            byte[] buffer = new byte[1024 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return "sha256:" + HexFormat.of().formatHex(digest.digest());
    }

    private static String paragraphDigest(String value) throws Exception {
        StringBuilder normalized = new StringBuilder();
        value.codePoints().filter(c -> !Character.isWhitespace(c) && !Character.isSpaceChar(c))
                .forEach(normalized::appendCodePoint);
        return digest(normalized.toString().getBytes(StandardCharsets.UTF_8));
    }

    private void paragraphs(Iterable<Paragraph> values, int depth) throws Exception {
        if (depth > 64) throw new IllegalArgumentException("nesting limit");
        for (Paragraph paragraph : values) {
            if (paragraphs.size() >= 100000) throw new IllegalArgumentException("paragraph limit");
            paragraphs.add(paragraphDigest(paragraph.getNormalString()));
            if (paragraph.getControlList() != null) {
                for (Control control : paragraph.getControlList()) control(control, depth + 1);
            }
        }
    }

    private void caption(Caption value, int depth) throws Exception {
        if (value != null) paragraphs(value.getParagraphList(), depth + 1);
    }

    private void textBox(TextBox value, int depth) throws Exception {
        if (value != null) paragraphs(value.getParagraphList(), depth + 1);
    }

    private void control(Control value, int depth) throws Exception {
        if (depth > 64) throw new IllegalArgumentException("nesting limit");
        if (value instanceof ControlTable table) {
            if (tables.size() >= 10000) throw new IllegalArgumentException("table limit");
            StringBuilder shape = new StringBuilder();
            shape.append(table.getTable().getRowCount()).append(',')
                    .append(table.getTable().getColumnCount()).append(';');
            for (var row : table.getRowList()) {
                for (var cell : row.getCellList()) {
                    var header = cell.getListHeader();
                    shape.append(header.getColIndex()).append(',').append(header.getRowIndex()).append(',')
                            .append(header.getColSpan()).append(',').append(header.getRowSpan()).append(',')
                            .append(header.getWidth()).append(',').append(header.getHeight()).append(';');
                    paragraphs(cell.getParagraphList(), depth + 1);
                }
            }
            tables.add(digest(shape.toString().getBytes(StandardCharsets.UTF_8)));
            caption(table.getCaption(), depth);
        } else if (value instanceof ControlEquation equation) {
            equations.add(digest(equation.getEQEdit().getScript().toUTF16LEString()
                    .getBytes(StandardCharsets.UTF_8)));
            caption(equation.getCaption(), depth);
        } else if (value instanceof GsoControl shape) {
            String name = switch (shape.getGsoType()) {
                case Picture -> "pic";
                case Container -> "container";
                case Rectangle -> "rect";
                case Ellipse -> "ellipse";
                case Arc -> "arc";
                case Polygon -> "polygon";
                case Curve -> "curve";
                case Line -> "line";
                case ObjectLinkLine -> "connectLine";
                default -> throw new IllegalArgumentException("unsupported compound/active object");
            };
            int count = shapes.get(name) + 1;
            if (count > 10000) throw new IllegalArgumentException("shape limit");
            shapes.put(name, count);
            if (shape instanceof ControlContainer group) {
                for (GsoControl child : group.getChildControlList()) control(child, depth + 1);
            } else if (shape instanceof ControlRectangle box) textBox(box.getTextBox(), depth);
            else if (shape instanceof ControlEllipse box) textBox(box.getTextBox(), depth);
            else if (shape instanceof ControlArc box) textBox(box.getTextBox(), depth);
            else if (shape instanceof ControlPolygon box) textBox(box.getTextBox(), depth);
            else if (shape instanceof ControlCurve box) textBox(box.getTextBox(), depth);
            caption(shape.getCaption(), depth);
        } else if (value instanceof ControlHeader header) paragraphs(header.getParagraphList(), depth + 1);
        else if (value instanceof ControlFooter footer) paragraphs(footer.getParagraphList(), depth + 1);
        else if (value instanceof ControlFootnote note) paragraphs(note.getParagraphList(), depth + 1);
        else if (value instanceof ControlEndnote note) paragraphs(note.getParagraphList(), depth + 1);
        else if (value instanceof ControlHiddenComment comment) paragraphs(comment.getParagraphList(), depth + 1);
        else if (!Set.of("SectionDefine", "ColumnDefine", "AutoNumber", "NewNumber", "PageHide",
                "PageNumberPosition", "Bookmark", "FIELD_CLICKHERE", "FIELD_DATE", "FIELD_DOCDATE",
                "FIELD_PATH", "FIELD_SUMMARY", "FIELD_USERINFO").contains(value.getType().name())) {
            throw new IllegalArgumentException("unsupported native control");
        }
    }

    private static String hashes(List<String> values) {
        // Values are computed SHA-256 identifiers, never arbitrary document text.
        values.sort(String::compareTo);
        return "[" + String.join(",", values.stream().map(v -> "\"" + v + "\"").toList()) + "]";
    }

    private void convert(Path source, Path candidate, Path evidence) throws Exception {
        if (!Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS)
                || Files.size(source) > 50L * 1024L * 1024L
                || Files.exists(candidate, LinkOption.NOFOLLOW_LINKS)
                || Files.exists(evidence, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("unsafe local boundary");
        }
        String sourceHash = fileDigest(source);
        HWPFile document = HWPReader.fromFile(source.toString());
        if (document == null) throw new IllegalArgumentException("unreadable HWP");
        int sections = document.getBodyText().getSectionList().size();
        if (sections < 1 || sections > 10000) throw new IllegalArgumentException("section limit");
        for (var binding : document.getDocInfo().getBinDataList()) {
            if (binding.getProperty().getType() != BinDataType.Embedding) {
                throw new IllegalArgumentException("linked or compound binary");
            }
        }
        List<String> binaries = new ArrayList<>();
        for (var binary : document.getBinData().getEmbeddedBinaryDataList()) {
            if (binaries.size() >= 10000) throw new IllegalArgumentException("binary limit");
            binaries.add(digest(binary.getData()));
        }
        for (var section : document.getBodyText().getSectionList()) {
            paragraphs(Arrays.asList(section.getParagraphs()), 0);
        }
        HWPXWriter.toFilepath(Hwp2Hwpx.toHWPX(document), candidate.toString());
        if (!sourceHash.equals(fileDigest(source))) throw new IllegalArgumentException("source changed");
        String shapeJson = "{" + String.join(",", shapes.entrySet().stream()
                .map(v -> "\"" + v.getKey() + "\":" + v.getValue()).toList()) + "}";
        String result = "{\"schema_version\":\"native-hwp-conversion-evidence/1.0\","
                + "\"source_sha256\":\"" + sourceHash + "\","
                + "\"candidate_sha256\":\"" + fileDigest(candidate) + "\","
                + "\"section_count\":" + sections + ","
                + "\"paragraph_sha256\":" + hashes(paragraphs) + ","
                + "\"table_sha256\":" + hashes(tables) + ","
                + "\"equation_sha256\":" + hashes(equations) + ","
                + "\"binary_sha256\":" + hashes(binaries) + ","
                + "\"shape_counts\":" + shapeJson + "}";
        Files.writeString(evidence, result + "\n", StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
    }

    public static void main(String[] args) {
        try {
            if (args.length != 3) throw new IllegalArgumentException("three local files required");
            new NativeHwpConverter().convert(Path.of(args[0]), Path.of(args[1]), Path.of(args[2]));
            System.out.println("native_hwp_conversion=CANDIDATE_CREATED");
        } catch (Exception error) {
            System.err.println("native_hwp_conversion=FAILED error_type=" + error.getClass().getSimpleName());
            System.exit(1);
        }
    }
}
