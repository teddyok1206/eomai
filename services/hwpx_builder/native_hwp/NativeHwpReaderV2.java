package eom.hwpx;

import java.nio.file.Path;
import java.io.ByteArrayInputStream;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;

import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.Section;
import kr.dogfoot.hwplib.object.bodytext.control.sectiondefine.BatangPageInfo;
import kr.dogfoot.hwplib.object.docinfo.bindata.BinDataCompress;
import kr.dogfoot.hwplib.object.docinfo.bindata.BinDataType;
import kr.dogfoot.hwplib.object.docinfo.BinData;
import kr.dogfoot.hwplib.reader.ForFileHeader;
import kr.dogfoot.hwplib.reader.bodytext.ForParagraphList;
import kr.dogfoot.hwplib.reader.bodytext.memo.ForMemo;
import kr.dogfoot.hwplib.reader.bodytext.paragraph.control.secd.ForBatangPageInfo;
import kr.dogfoot.hwplib.reader.docinfo.ForDocInfo;
import kr.dogfoot.hwplib.util.compoundFile.reader.CompoundFileReader;
import kr.dogfoot.hwplib.util.compoundFile.reader.StreamReader;
import kr.dogfoot.hwplib.org.apache.poi.hpsf.PropertySet;
import kr.dogfoot.hwplib.org.apache.poi.hpsf.SummaryInformation;
import kr.dogfoot.hwplib.object.fileheader.FileVersion;

/** Versioned file adapter around the existing public readers; never skips an unknown tail. */
final class NativeHwpReaderV2 {
    record AuxiliaryMasterPage(int sourceSection, String kind, int ordinal, BatangPageInfo page,
            String rawRecordSha256, int sourceStart, int sourceEnd) {}
    record UnboundBinaryMember(String memberPath, String rawSha256, int sizeBytes) {}
    record Result(HWPFile document, List<AuxiliaryMasterPage> auxiliaryMasterPages,
            List<UnboundBinaryMember> unboundBinaryMembers) {}

    static Map<String, BinData> binaryBindings(HWPFile file) {
        Map<String, BinData> bindings = new HashMap<>();
        var storageIds = new HashSet<Integer>();
        for (BinData binding : file.getDocInfo().getBinDataList()) {
            int storageId = binding.getBinDataID();
            String extension = binding.getExtensionForEmbedding();
            if (binding.getProperty().getType() != BinDataType.Embedding
                    || storageId < 1 || storageId > 65535 || extension == null
                    || !extension.matches("[A-Za-z0-9]{1,12}") || !storageIds.add(storageId)) {
                throw new IllegalArgumentException("NATIVE_HWP_BINARY_BINDING_INVALID");
            }
            String member = String.format(Locale.ROOT, "BIN%04X.%s", storageId, extension)
                    .toLowerCase(Locale.ROOT);
            if (bindings.putIfAbsent(member, binding) != null) {
                throw new IllegalArgumentException("NATIVE_HWP_BINARY_BINDING_DUPLICATED");
            }
        }
        return bindings;
    }

    static boolean binaryCompressed(BinData binding, boolean storageDefault) {
        BinDataCompress compression = binding.getProperty().getCompress();
        return compression == BinDataCompress.Compress
                || compression == BinDataCompress.ByStorageDefault && storageDefault;
    }

    static UnboundBinaryMember unboundBinary(String name, byte[] raw) throws Exception {
        return new UnboundBinaryMember("BinData/" + name,
                "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw)),
                raw.length);
    }

    static final class SectionStream extends StreamReader {
        final byte[] original;
        SectionStream(byte[] bytes, FileVersion version) {
            original = bytes;
            is = new ByteArrayInputStream(bytes);
            size = bytes.length;
            fileVersion = version;
        }
    }

    static Result read(Path path) throws Exception {
        HWPFile file = new HWPFile();
        List<AuxiliaryMasterPage> auxiliary = new ArrayList<>();
        List<UnboundBinaryMember> unbound = new ArrayList<>();
        CompoundFileReader compound = new CompoundFileReader(path.toFile());
        try {
            StreamReader header = compound.getChildStreamReader("FileHeader", false, null);
            try { ForFileHeader.read(file.getFileHeader(), header); }
            finally { header.close(); }
            if (file.getFileHeader().hasPassword() || file.getFileHeader().isDistribution()) {
                throw new IllegalArgumentException("NATIVE_HWP_SOURCE_PROTECTED");
            }
            boolean compressed = file.getFileHeader().isCompressed();
            var version = file.getFileHeader().getVersion();
            StreamReader info = compound.getChildStreamReader("DocInfo", compressed, version);
            try { new ForDocInfo().read(file.getDocInfo(), info); }
            finally { info.close(); }
            int count = file.getDocInfo().getDocumentProperties().getSectionCount();
            if (count < 1 || count > 10000) throw new IllegalArgumentException("section limit");
            compound.moveChildStorage("BodyText");
            try {
                for (int index = 0; index < count; index++) {
                    StreamReader input = compound.getChildStreamReader("Section" + index, compressed, version);
                    byte[] sectionBytes;
                    try {
                        long bytes = input.getSize();
                        if (bytes < 0 || bytes > 64L * 1024 * 1024) {
                            throw new IllegalArgumentException("NATIVE_HWP_SECTION_SIZE_LIMIT");
                        }
                        sectionBytes = new byte[(int) bytes];
                        input.readBytes(sectionBytes);
                    } finally { input.close(); }
                    SectionStream stream = new SectionStream(sectionBytes, version);
                    try {
                        stream.setDocInfo(file.getDocInfo());
                        Section section = file.getBodyText().addNewSection();
                        ForParagraphList.read(section, stream);
                        readTrailingRecords(file, stream, auxiliary, index, 0, index == count - 1);
                    } finally { stream.close(); }
                }
            } finally { compound.moveParentStorage(); }
            Map<String, BinData> bindings = binaryBindings(file);
            var resolvedBindings = new HashSet<String>();
            if (compound.isChildStorage("BinData")) {
                compound.moveChildStorage("BinData");
                try {
                    long total = 0;
                    String[] names = compound.listChildNames().toArray(String[]::new);
                    if (names.length > 10000) throw new IllegalArgumentException("NATIVE_HWP_BINARY_COUNT_LIMIT");
                    Arrays.sort(names);
                    var actualMembers = new HashSet<String>();
                    for (String name : names) {
                        if (!name.matches("BIN[0-9A-Fa-f]{4}\\.[A-Za-z0-9]{1,12}")) {
                            throw new IllegalArgumentException("NATIVE_HWP_BINARY_NAME_UNSUPPORTED");
                        }
                        String key = name.toLowerCase(Locale.ROOT);
                        if (!actualMembers.add(key)) throw new IllegalArgumentException("NATIVE_HWP_BINARY_MEMBER_DUPLICATED");
                        BinData binding = bindings.get(key);
                        // Storage IDs are not the ordinal picture-reference IDs. Only the
                        // exact DocInfo storage ID + extension supplies a compression flag.
                        boolean inflate = binding != null && binaryCompressed(binding, compressed);
                        StreamReader binary = compound.getChildStreamReader(name, inflate, null);
                        try {
                            long size = binary.getSize();
                            total += size;
                            if (size < 0 || size > 64L * 1024 * 1024 || total > 128L * 1024 * 1024) {
                                throw new IllegalArgumentException("NATIVE_HWP_BINARY_SIZE_LIMIT");
                            }
                            byte[] bytes = new byte[(int) size];
                            binary.readBytes(bytes);
                            if (binding == null) {
                                // Unknown compression cannot be guessed. Retain raw identity
                                // in the proof and original; never attach it as a question image.
                                unbound.add(unboundBinary(name, bytes));
                            } else {
                                file.getBinData().addNewEmbeddedBinaryData(name, bytes,
                                        binding.getProperty().getCompress());
                                resolvedBindings.add(key);
                            }
                        } finally { binary.close(); }
                    }
                } finally { compound.moveParentStorage(); }
            }
            if (!resolvedBindings.equals(bindings.keySet())) {
                throw new IllegalArgumentException("NATIVE_HWP_BINARY_BOUND_MEMBER_MISSING");
            }
            if (compound.isChildStream("\u0005HwpSummaryInformation")) {
                var summary = compound.getChildInputStream("\u0005HwpSummaryInformation");
                try { file.setSummaryInformation(new SummaryInformation(new PropertySet(summary))); }
                finally { summary.close(); }
            }
            // Script bytes remain in the immutable original. No script is executed or copied
            // into an output package; native question structures and memo bodies are explicit.
            return new Result(file, List.copyOf(auxiliary), List.copyOf(unbound));
        } finally { compound.close(); }
    }

    static void readTrailingRecords(HWPFile file, SectionStream stream,
            List<AuxiliaryMasterPage> auxiliary, int sourceSection, int ordinal,
            boolean allowMemos) throws Exception {
        int records = 0;
        while (!stream.isEndOfStream()) {
            if (++records > 10000) throw new IllegalArgumentException("NATIVE_HWP_TAIL_LIMIT");
            if (stream.getCurrentRecordHeader() == null || !stream.isImmediatelyAfterReadingHeader()) {
                stream.readRecordHeader();
            }
            long before = stream.getCurrentPosition();
            short tag = stream.getCurrentRecordHeader().getTagID();
            if (tag == 72) {
                int start = recordStart(stream);
                BatangPageInfo page = new BatangPageInfo();
                ForBatangPageInfo.read(page, stream);
                int end = stream.isEndOfStream() ? (int) stream.getCurrentPosition() : recordStart(stream);
                if (start < 0 || end <= start || end > stream.original.length) {
                    throw new IllegalArgumentException("NATIVE_HWP_TAIL_RANGE_INVALID");
                }
                String hash = "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                        .digest(Arrays.copyOfRange(stream.original, start, end)));
                String kind = ordinal == 0 ? "LAST" : ordinal == 1 ? "ANY" : "TRAILING";
                auxiliary.add(new AuxiliaryMasterPage(sourceSection, kind, ordinal++, page, hash, start, end));
            } else if (tag == 93 && allowMemos) {
                ForMemo.read(file.getBodyText().addNewMemo(), stream);
            } else {
                throw new IllegalArgumentException("NATIVE_HWP_TRAILING_RECORD_UNSUPPORTED");
            }
            if (!stream.isEndOfStream() && stream.getCurrentPosition() <= before) {
                throw new IllegalArgumentException("NATIVE_HWP_READER_NO_PROGRESS");
            }
        }
    }

    private static int recordStart(StreamReader stream) {
        long offset = stream.getCurrentPosition();
        if (stream.isImmediatelyAfterReadingHeader()) {
            offset -= stream.getCurrentRecordHeader().getSize() >= 4095 ? 8 : 4;
        }
        if (offset < 0 || offset > 64L * 1024 * 1024) throw new IllegalArgumentException("NATIVE_HWP_TAIL_RANGE_INVALID");
        return (int) offset;
    }
}
