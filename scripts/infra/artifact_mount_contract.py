from __future__ import annotations

import argparse
from pathlib import Path


class ArtifactMountContractError(ValueError):
    """Raised when the reviewed CIFS fstab identity is missing or ambiguous."""


def rewrite_fstab(
    source_path: Path,
    output_path: Path,
    *,
    expected_source: str,
    mount_point: str,
    uid: int,
    gid: int,
) -> None:
    lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) >= 2 and fields[0] == expected_source and fields[1] == mount_point:
            if len(fields) != 6 or fields[2] != "cifs":
                raise ArtifactMountContractError("Artifact fstab entry shape is invalid")
            matches.append(index)
    if len(matches) != 1:
        raise ArtifactMountContractError("Artifact fstab entry is not unique")

    index = matches[0]
    fields = lines[index].strip().split()
    options = fields[3].split(",")
    credential_pointers = [option for option in options if option.startswith("credentials=/")]
    if len(credential_pointers) != 1:
        raise ArtifactMountContractError("Artifact credential pointer is not unique")
    if any(option.startswith(("password=", "pass=")) for option in options):
        raise ArtifactMountContractError("Inline Artifact credentials are forbidden")

    replace_keys = {"uid", "gid", "file_mode", "dir_mode"}
    required_flags = ("forceuid", "forcegid", "nounix", "nosuid", "nodev", "noexec")
    options = [
        option
        for option in options
        if option.split("=", 1)[0] not in replace_keys and option not in required_flags
    ]
    options.extend(required_flags)
    options.extend((f"uid={uid}", f"gid={gid}", "file_mode=0640", "dir_mode=0770"))
    fields[3] = ",".join(options)
    lines[index] = "\t".join(fields) + "\n"
    output_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("expected_source")
    parser.add_argument("mount_point")
    parser.add_argument("uid", type=int)
    parser.add_argument("gid", type=int)
    arguments = parser.parse_args()
    rewrite_fstab(
        arguments.source_path,
        arguments.output_path,
        expected_source=arguments.expected_source,
        mount_point=arguments.mount_point,
        uid=arguments.uid,
        gid=arguments.gid,
    )


if __name__ == "__main__":
    main()
