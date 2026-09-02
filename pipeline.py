"""M6 — orchestrator CLI for the face identification and verification pipeline."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description=(
            "Identify a face in an image against publicly indexed images and "
            "anchor the verified result on Polygon Amoy."
        ),
    )
    parser.add_argument(
        "--image",
        help="Path to the query image to run through the pipeline.",
    )
    parser.add_argument(
        "--verify",
        metavar="RECORD_HASH",
        help="Verify an existing 0x-prefixed record hash against the on-chain record.",
    )
    parser.add_argument(
        "--tamper-demo",
        action="store_true",
        help="After anchoring, mutate one payload field to show the hash no longer matches.",
    )
    return parser


def main() -> None:
    build_parser().parse_args()


if __name__ == "__main__":
    main()
