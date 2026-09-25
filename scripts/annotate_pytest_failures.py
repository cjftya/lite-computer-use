"""Surface pytest failures in GitHub check annotations when job logs are private."""

import sys
import xml.etree.ElementTree as ET


def main(path: str) -> None:
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        for result in case:
            if result.tag not in {"failure", "error"}:
                continue
            name = f"{case.get('classname', '')}.{case.get('name', '')}"
            detail = (result.text or result.get("message") or "Unknown pytest failure").strip()
            detail = detail[:3000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title={name}::{detail}")


if __name__ == "__main__":
    main(sys.argv[1])
