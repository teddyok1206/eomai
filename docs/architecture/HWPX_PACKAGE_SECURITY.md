# HWPX Package Security

Every HWPX is an untrusted ZIP containing untrusted XML and binary data. Validation happens before
extraction, and extraction writes only regular files beneath a newly created workspace directory.

## ZIP Limits

| Control | POC limit |
| --- | ---: |
| Package bytes | 50 MiB |
| Entries | 2,000 |
| One member | 25 MiB |
| Total uncompressed | 200 MiB |
| Compression ratio | 100:1 |
| Entry name | 240 characters |

Absolute names, `..`, backslashes, NULs, duplicate names, case-fold collisions, symlinks, devices,
and workspace escapes are rejected. Nested archives are not extracted. A single package member is
read only after its central-directory size and ratio pass the bounds.

## XML Controls

The parser rejects DTD and entity declarations before parsing. It uses lxml with entity resolution,
network access, DTD loading, recovery mode, and huge-tree mode disabled. XInclude, XML over 10 MiB,
and depth over 128 are rejected. Serialization preserves the observed XML declaration, BOM, and
declaration newline; it does not recover malformed input.

## Active Content

Reference import fails when the analyzer identifies script or macro parts, OLE, encryption,
signatures, external links, executables, or embedded package extensions. Preview text and image
parts are passive but non-authoritative. Unknown passive parts are preserved and reported.

## Validation Evidence

The structural report records stable check IDs, severity, package part, and a hash of bounded
evidence. It never embeds full XML or document content. Errors expose machine codes and sanitized
summaries rather than archive paths, credentials, or payloads.
