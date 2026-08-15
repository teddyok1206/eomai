# HWPX Format References

Checked: 2026-08-15 UTC

This implementation was developed by referring to Hancom's public HWP/OWPML format material. The
published documents and the paid or licensed KS text are not copied into this repository.

## Authoritative Sources

1. [Hancom HWP/OWPML format disclosure](https://www.store.hancom.com/support/downloadCenter/hwpOwpml)
   states that Hancom publishes HWP/HWPML format material and describes `.hwpx` as an OWPML form
   supported by Hancom Office. Its copyright notice requires an acknowledgement in products derived
   from the material; this notice is therefore included here and in the HWPX CLI documentation.
2. [Hancom Tech: HWPX format structure](https://tech.hancom.com/hwpxformat/) (2025-02-26)
   describes HWPX as a ZIP/XML package. It identifies `mimetype`, `version.xml`, `BinData/`,
   `Contents/content.hpf`, `Contents/header.xml`, section XML, `META-INF/`, `Scripts/`, and `Preview/`.
   It also states that `content.hpf` contains metadata, manifest, and ordered spine information, and
   that document text is commonly under paragraph/run/text elements.
3. [KS X 6101 national-standard metadata](https://www.standard.go.kr/KSCI/standardIntro/getStandardSearchView.do?ksNo=KSX6101&menuId=503&tmprKsNo=KSX6101&topMenuId=502)
   identifies the standard as "Open Word-Processor Markup Language (OWPML) document structure",
   issued 2011-12-30 and last confirmed 2024-10-30. The listing covers document representation,
   binary-HWP compatibility, compatibility assessment, and metadata extension.
4. [Hancom Office help: HWPX](https://help.hancom.com/hoffice130_assistant/ko-KR/Hwp/file/open/open%28other%29.htm)
   confirms that HWPX is an XML-based open format whose content representation is based on KS X 6101.

## Applied Boundary

The POC does not infer namespace URIs, object IDs, equation storage, package version, or relationship
semantics from these summaries. A Hancom-saved reference is authoritative for those details. The
importer records and preserves its `version.xml`, namespace profile, entry order, compression method,
unknown parts, manifest order, and spine order. If published material and an actual reference differ,
the importer report records the observed difference; it does not rewrite the reference to a presumed
newer profile.

The exact KS text and Hancom PDF files remain external. Only source name, URL, check date, public
metadata, and the narrow engineering conclusions above are retained.
