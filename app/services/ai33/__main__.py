"""Explicit, isolated local validation; no network at application startup."""

import argparse
import json
import os
from pathlib import Path

from .client import AI33Client, AI33Error
from .images import ImageJob


def main():
    parser = argparse.ArgumentParser(description="Conector isolado AI33.Pro — imagens")
    parser.add_argument("action", choices=["models", "price", "generate"])
    parser.add_argument("--model")
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--resolution", default="2K")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--max-credits", type=float)
    parser.add_argument("--wait-minutes", type=float, default=45)
    args = parser.parse_args()
    client = AI33Client(os.environ.get("AI33_API_KEY"))
    if args.action == "models":
        print(json.dumps(client.models(), ensure_ascii=False, indent=2))
        return
    if not args.model:
        parser.error("--model é obrigatório; consulte models primeiro")
    parameters = {"aspect_ratio": args.aspect_ratio, "resolution": args.resolution}
    if args.action == "price":
        client.validate(args.model, parameters, "Quote validation")
        print(json.dumps({"credits": client.price(args.model, parameters)}))
        return
    if args.prompt_file is None or args.directory is None or args.max_credits is None:
        parser.error("generate exige --prompt-file, --directory e --max-credits")
    path = ImageJob(client, args.directory).run(
        model_id=args.model, parameters=parameters,
        prompt=args.prompt_file.read_text(encoding="utf-8-sig"), max_credits=args.max_credits,
        wait_seconds=args.wait_minutes * 60,
    )
    print(f"Imagem salva: {path}")


if __name__ == "__main__":
    try:
        main()
    except AI33Error as exc:
        raise SystemExit(str(exc)) from None
