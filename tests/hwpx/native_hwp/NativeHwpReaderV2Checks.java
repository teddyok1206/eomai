package eom.hwpx;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.control.ControlField;
import kr.dogfoot.hwplib.object.bodytext.control.ControlType;
import kr.dogfoot.hwplib.object.docinfo.BinData;
import kr.dogfoot.hwplib.object.docinfo.bindata.BinDataType;
import kr.dogfoot.hwplib.object.docinfo.bindata.BinDataCompress;
import kr.dogfoot.hwpxlib.object.content.section_xml.paragraph.object.Equation;

/** Synthetic record streams only; no user documents, DB, model or network. */
public final class NativeHwpReaderV2Checks {
    private static byte[] record(int tag, byte[] payload) {
        return recordLevel(tag, 0, payload);
    }

    private static byte[] recordLevel(int tag, int level, byte[] payload) {
        return ByteBuffer.allocate(4 + payload.length).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(tag | level << 10 | payload.length << 20).put(payload).array();
    }

    private static byte[] concatenate(byte[] first, byte[] second) {
        byte[] result = Arrays.copyOf(first, first.length + second.length);
        System.arraycopy(second, 0, result, first.length, second.length);
        return result;
    }

    private static ControlField field(String command) {
        ControlField field = new ControlField(ControlType.FIELD_UNKNOWN.getCtrlId());
        field.getHeader().getCommand().fromUTF16LEString(command);
        return field;
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("synthetic native reader check failed");
    }

    private static void rejectTail(byte[] bytes, String code) throws Exception {
        var stream = new NativeHwpReaderV2.SectionStream(bytes, null);
        stream.setDocInfo(new HWPFile().getDocInfo());
        stream.readRecordHeader();
        try {
            NativeHwpReaderV2.readTrailingRecords(new HWPFile(), stream, new ArrayList<>(), 0, 0, true);
            throw new AssertionError("unknown trailing record accepted");
        } catch (IllegalArgumentException error) {
            check(error.getMessage().equals(code));
        } finally { stream.close(); }
    }

    private static BinData binding(int storageId, String extension, BinDataCompress compression) {
        BinData result = new BinData();
        result.setBinDataID(storageId);
        result.setExtensionForEmbedding(extension);
        result.getProperty().setType(BinDataType.Embedding);
        result.getProperty().setCompress(compression);
        return result;
    }

    private static Equation equation(String script) {
        Equation equation = new Equation();
        equation.createScript();
        equation.script().addText(script);
        return equation;
    }

    private static void binaryAndEquationChecks() throws Exception {
        HWPFile source = new HWPFile();
        BinData jpeg = binding(26, "jpg", BinDataCompress.NoCompress);
        BinData png = binding(14, "png", BinDataCompress.ByStorageDefault);
        source.getDocInfo().getBinDataList().add(jpeg);
        source.getDocInfo().getBinDataList().add(png);
        var map = NativeHwpReaderV2.binaryBindings(source);
        check(map.size() == 2 && map.get("bin001a.jpg") == jpeg);
        check(!NativeHwpReaderV2.binaryCompressed(map.get("bin001a.jpg"), true));
        check(NativeHwpReaderV2.binaryCompressed(map.get("bin000e.png"), true));
        check(!NativeHwpReaderV2.binaryCompressed(map.get("bin000e.png"), false));
        // Same storage ID but a different extension is not this binding.
        check(!map.containsKey("bin001a.png"));
        byte[] unboundPng = new byte[]{(byte) 0x89, 0x50, 0x4e, 0x47};
        var unbound = NativeHwpReaderV2.unboundBinary("BIN001A.png", unboundPng);
        check(unbound.memberPath().equals("BinData/BIN001A.png") && unbound.sizeBytes() == 4);
        check(unbound.rawSha256().equals("sha256:0f4636c78f65d3639ece5a064b5ae753e3408614a14fb18ab4d7540d2c248543"));

        Equation crlf = equation("a\r\nb<&>");
        Equation lflf = equation("a\n\nb<&>");
        Map<String, String> scripts = NativeHwpWriterV2.protectScripts(List.of(crlf, lflf));
        check(scripts.size() == 1 && crlf.script().text().equals("EOM_NATIVE_EQ_0"));
        check(lflf.script().text().equals("a\n\nb<&>"));
        var restored = new HashSet<String>();
        String xml = NativeHwpWriterV2.restoreScripts("<hp:script>EOM_NATIVE_EQ_0</hp:script>", scripts, restored);
        check(xml.equals("<hp:script>a&#13;\nb&lt;&amp;&gt;</hp:script>"));
        check(restored.equals(scripts.keySet()));
        try {
            NativeHwpWriterV2.restoreScripts("<hp:script>EOM_NATIVE_EQ_0</hp:script>", scripts, restored);
            throw new AssertionError("duplicated equation marker accepted");
        } catch (IllegalArgumentException expected) { }
        try {
            NativeHwpWriterV2.protectScripts(List.of(equation("x\r\ny"), equation("EOM_NATIVE_EQ_0")));
            throw new AssertionError("source marker collision accepted");
        } catch (IllegalArgumentException expected) { }
    }

    public static void main(String[] args) throws Exception {
        binaryAndEquationChecks();
        byte[] listHeader = record(72, ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(1).putInt(0).putInt(12345).putInt(6789).array());
        byte[] paragraphHeader = recordLevel(66, 1, ByteBuffer.allocate(22).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(0x80000000).put(new byte[18]).array());
        byte[] list = concatenate(listHeader, paragraphHeader);
        byte[] two = concatenate(list, list);
        var stream = new NativeHwpReaderV2.SectionStream(two, null);
        stream.setDocInfo(new HWPFile().getDocInfo());
        stream.readRecordHeader();
        List<NativeHwpReaderV2.AuxiliaryMasterPage> pages = new ArrayList<>();
        NativeHwpReaderV2.readTrailingRecords(new HWPFile(), stream, pages, 0, 0, true);
        check(stream.isEndOfStream());
        check(pages.size() == 2);
        check(pages.get(0).sourceStart() == 0 && pages.get(0).sourceEnd() == list.length);
        check(pages.get(1).sourceStart() == list.length && pages.get(1).sourceEnd() == two.length);
        check(pages.get(0).rawRecordSha256().equals(pages.get(1).rawRecordSha256()));
        check(pages.get(0).page().getListHeader().getTextWidth() == 12345);
        check(pages.get(0).kind().equals("LAST") && pages.get(1).kind().equals("ANY"));
        stream.close();
        rejectTail(record(94, new byte[4]), "NATIVE_HWP_TRAILING_RECORD_UNSUPPORTED");
        rejectTail(concatenate(list, record(94, new byte[4])), "NATIVE_HWP_TRAILING_RECORD_UNSUPPORTED");
        check(NativeHwpConverter.validatedMemoIndex(field("MEMO/0/3/0/0/author/\\;;")) == 3);
        check(NativeHwpConverter.validatedMemoIndex(field("MEMO/0/4/0/0/author/")) == 4);
        for (String command : List.of("MEMO/0/3/0/0/author/EXEC", "MEMO/0/3/0/0/author/\\;;/extra",
                "SCRIPT/0/3/0/0/author/", "MEMO/0/-1/0/0/author/", "MEMO/0/3/0/0/author")) {
            try {
                NativeHwpConverter.validatedMemoIndex(field(command));
                throw new AssertionError("unsupported field accepted");
            } catch (IllegalArgumentException expected) { }
        }
        System.out.println("native_hwp_reader_v2_synthetic=PASS");
    }
}
