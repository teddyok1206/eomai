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
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.HashSet;
import java.util.EmptyStackException;

import kr.dogfoot.hwp2hwpx.Hwp2Hwpx;
import kr.dogfoot.hwp2hwpx.Parameter;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.control.*;
import kr.dogfoot.hwplib.object.bodytext.control.gso.*;
import kr.dogfoot.hwplib.object.bodytext.control.gso.caption.Caption;
import kr.dogfoot.hwplib.object.bodytext.control.gso.textbox.TextBox;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.object.docinfo.bindata.BinDataType;
import kr.dogfoot.hwplib.object.bodytext.control.sectiondefine.BatangPageInfo;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.object.content.masterpage_xml.enumtype.MasterPageType;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

/** File-only adapter. No network, NAS, credentials, orchestration or publication. */
public final class NativeHwpConverter {
    private final List<String> paragraphs = new ArrayList<>();
    private final List<String> tables = new ArrayList<>();
    private final List<String> equations = new ArrayList<>();
    private final Map<String, Integer> shapes = new LinkedHashMap<>();
    private final boolean nativeV2;
    private final Set<BatangPageInfo> countedMasters = Collections.newSetFromMap(new IdentityHashMap<>());
    private final Set<Long> memoIndexes = new HashSet<>();

    private NativeHwpConverter() {
        this(false);
    }

    private NativeHwpConverter(boolean nativeV2) {
        this.nativeV2 = nativeV2;
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

    private void masterPage(BatangPageInfo page) throws Exception {
        if (countedMasters.add(page)) paragraphs(page.getParagraphList(), 0);
    }

    static long validatedMemoIndex(ControlField field) {
        String command = field.getHeader().getCommand() == null ? "" : field.getHeader().getCommand().toUTF16LEString();
        String[] parts = command.split("/", -1);
        if (!field.getType().name().equals("FIELD_UNKNOWN") || command.length() > 4096
                || parts.length != 7 || !parts[0].equals("MEMO")
                || !(parts[6].isEmpty() || parts[6].equals("\\;;"))) {
            throw new IllegalArgumentException("NATIVE_HWP_FIELD_UNSUPPORTED");
        }
        for (int index : new int[]{1, 2, 3, 4}) {
            long number;
            try { number = Long.parseLong(parts[index]); }
            catch (NumberFormatException error) { throw new IllegalArgumentException("NATIVE_HWP_MEMO_INVALID"); }
            if (number < 0 || number > 0xffffffffL) throw new IllegalArgumentException("NATIVE_HWP_MEMO_INVALID");
        }
        return Long.parseLong(parts[2]);
    }

    private void memoField(ControlField field) {
        if (!memoIndexes.add(validatedMemoIndex(field))) {
            throw new IllegalArgumentException("NATIVE_HWP_MEMO_REFERENCE_DUPLICATED");
        }
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
        else if (nativeV2 && value instanceof ControlSectionDefine section) {
            for (BatangPageInfo page : section.getBatangPageInfoList()) masterPage(page);
        }
        else if (nativeV2 && value instanceof ControlField field
                && value.getType().name().equals("FIELD_UNKNOWN")) memoField(field);
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

    private static String auxiliaryMetadata(NativeHwpReaderV2.AuxiliaryMasterPage retained) {
        var header = retained.page().getListHeader();
        return "\"source_section\":" + retained.sourceSection()
                + ",\"kind\":\"" + retained.kind() + "\",\"ordinal\":" + retained.ordinal()
                + ",\"flags\":" + header.getProperty().getValue() + ",\"width\":" + header.getTextWidth()
                + ",\"height\":" + header.getTextHeight()
                + ",\"raw_record_sha256\":\"" + retained.rawRecordSha256() + "\""
                + ",\"source_start\":" + retained.sourceStart() + ",\"source_end\":" + retained.sourceEnd();
    }

    private String shapeJson() {
        return "{" + String.join(",", shapes.entrySet().stream()
                .map(v -> "\"" + v.getKey() + "\":" + v.getValue()).toList()) + "}";
    }

    private void convert(Path source, Path candidate, Path evidence) throws Exception {
        if (!Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS)
                || Files.size(source) > 50L * 1024L * 1024L
                || Files.exists(candidate, LinkOption.NOFOLLOW_LINKS)
                || Files.exists(evidence, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("unsafe local boundary");
        }
        String sourceHash = fileDigest(source);
        NativeHwpReaderV2.Result read = nativeV2 ? NativeHwpReaderV2.read(source) : null;
        HWPFile document = nativeV2 ? read.document() : HWPReader.fromFile(source.toString());
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
        HWPXFile converted;
        List<String> auxiliary = new ArrayList<>();
        List<String> auxiliaryExceptions = new ArrayList<>();
        if (nativeV2) {
            Set<Long> bodies = new HashSet<>();
            var memoBodies = document.getBodyText().getMemoList();
            if (memoBodies != null) for (var memo : memoBodies) {
                long number = memo.getMemoList().getMemoIndex();
                if (!memoIndexes.contains(number) || !bodies.add(number)) {
                    throw new IllegalArgumentException("NATIVE_HWP_MEMO_BODY_UNRESOLVED");
                }
                paragraphs(memo.getParagraphList(), 0);
            }
            if (!bodies.equals(memoIndexes)) throw new IllegalArgumentException("NATIVE_HWP_MEMO_BODY_MISSING");
            Parameter parameter = new Parameter(document, new HWPXFile());
            new NativeConversionV2(parameter).convert();
            if (!parameter.fieldBeginStack().empty()) {
                throw new IllegalArgumentException("NATIVE_HWP_BODY_FIELD_UNBALANCED");
            }
            converted = parameter.hwpx().file();
            for (var retained : read.auxiliaryMasterPages()) {
                int ordinal = converted.masterPageXMLFileList().count();
                String id = "masterpage" + ordinal;
                String member = "Contents/" + id + ".xml";
                var master = converted.masterPageXMLFileList().addNew();
                master.idAnd(id).typeAnd(retained.kind().equals("LAST") ? MasterPageType.LAST_PAGE : MasterPageType.OPTIONAL_PAGE)
                        .pageNumberAnd(0).pageDuplicateAnd(false).pageFront(false);
                try {
                    parameter.subListConverter().convertForMasterPage(master, retained.page());
                    if (!parameter.fieldBeginStack().empty()) throw new EmptyStackException();
                } catch (EmptyStackException malformedField) {
                    // This exemption is only for explicitly unreferenced auxiliary decoration.
                    // Main question conversion above has no exemption and no fabricated fields.
                    converted.masterPageXMLFileList().remove(master);
                    parameter.fieldBeginStack().clear();
                    NativeHwpConverter evidenceOnly = new NativeHwpConverter(true);
                    evidenceOnly.paragraphs(retained.page().getParagraphList(), 0);
                    auxiliaryExceptions.add("{" + auxiliaryMetadata(retained)
                            + ",\"code\":\"AUXILIARY_MASTERPAGE_FIELD_INVALID\""
                            + ",\"paragraph_sha256\":" + hashes(evidenceOnly.paragraphs)
                            + ",\"table_sha256\":" + hashes(evidenceOnly.tables)
                            + ",\"equation_sha256\":" + hashes(evidenceOnly.equations)
                            + ",\"shape_counts\":" + evidenceOnly.shapeJson() + "}");
                    continue;
                }
                masterPage(retained.page());
                converted.contentHPFFile().manifest().addNew().idAnd(id).hrefAnd(member).mediaType("application/xml");
                auxiliary.add("{\"member_path\":\"" + member + "\"," + auxiliaryMetadata(retained) + "}");
            }
        } else converted = Hwp2Hwpx.toHWPX(document);
        if (nativeV2) NativeHwpWriterV2.write(converted, candidate);
        else HWPXWriter.toFilepath(converted, candidate.toString());
        if (!sourceHash.equals(fileDigest(source))) throw new IllegalArgumentException("source changed");
        List<String> warnings = new ArrayList<>();
        if (!auxiliary.isEmpty()) warnings.add("\"AUXILIARY_MASTERPAGE_APPLICATION_UNRESOLVED\"");
        if (!auxiliaryExceptions.isEmpty()) warnings.add("\"AUXILIARY_MASTERPAGE_FIELD_INVALID\"");
        if (nativeV2 && !read.unboundBinaryMembers().isEmpty()) {
            warnings.add("\"UNBOUND_BINARY_MEMBERS_RETAINED_IN_SOURCE\"");
        }
        String v2 = nativeV2 ? ",\"masterpage_count\":" + countedMasters.size() + ",\"memo_count\":" + memoIndexes.size()
                + ",\"auxiliary_master_pages\":[" + String.join(",", auxiliary) + "]"
                + ",\"auxiliary_exceptions\":[" + String.join(",", auxiliaryExceptions) + "]"
                + ",\"unbound_binary_members\":[" + String.join(",", read.unboundBinaryMembers().stream()
                        .map(member -> "{\"member_path\":\"" + member.memberPath()
                                + "\",\"raw_sha256\":\"" + member.rawSha256()
                                + "\",\"size_bytes\":" + member.sizeBytes() + "}").toList()) + "]"
                + ",\"whole_paper_layout\":\"NOT_VERIFIED\""
                + ",\"warnings\":[" + String.join(",", warnings) + "]" : "";
        String result = "{\"schema_version\":\"native-hwp-conversion-evidence/" + (nativeV2 ? "2.0" : "1.0") + "\","
                + "\"source_sha256\":\"" + sourceHash + "\","
                + "\"candidate_sha256\":\"" + fileDigest(candidate) + "\","
                + "\"section_count\":" + sections + ","
                + "\"paragraph_sha256\":" + hashes(paragraphs) + ","
                + "\"table_sha256\":" + hashes(tables) + ","
                + "\"equation_sha256\":" + hashes(equations) + ","
                + "\"binary_sha256\":" + hashes(binaries) + ","
                + "\"shape_counts\":" + shapeJson() + v2 + "}";
        Files.writeString(evidence, result + "\n", StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
    }

    private static final class NativeConversionV2 extends Hwp2Hwpx {
        NativeConversionV2(Parameter parameter) { super(parameter); }
    }

    static void convertV2(Path source, Path candidate, Path evidence) throws Exception {
        new NativeHwpConverter(true).convert(source, candidate, evidence);
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
