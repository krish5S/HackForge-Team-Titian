"""Read-only connectivity/model check; optional real task calls, never policy activation."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv
from app.llm.client import LLMError, list_gemini_models, extract_receipt_fields, compile_policy_text
from app.policy import configure_compiler, compile_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ocr-file', type=Path, help='Actual saved OCR text to exercise extraction')
    parser.add_argument('--policy-file', type=Path, help='Actual numbered policy to run three-call compiler checks')
    args = parser.parse_args()
    load_dotenv(ROOT / 'backend' / '.env', override=False)
    try:
        models = list_gemini_models()
        print('Available model IDs:')
        for model in models:
            print(model)
        selected = os.getenv('RECEIPT_LLM_MODEL')
        if not selected:
            print('Set RECEIPT_LLM_MODEL to an available text model before task checks.')
            return 1 if args.ocr_file or args.policy_file else 0
        if selected not in models:
            raise LLMError('Configured model is not in the service model listing')
        print('Configured model is listed; task support still requires a successful completion.')
        if args.ocr_file or args.policy_file:
            if os.getenv('RECEIPT_LLM_PROVIDER') != 'gemini':
                raise LLMError('Task check requires RECEIPT_LLM_PROVIDER=gemini')
        if args.ocr_file:
            import hashlib
            text = args.ocr_file.read_text()
            with tempfile.TemporaryDirectory() as directory:
                result = extract_receipt_fields(text, hashlib.sha256(text.encode()).hexdigest(), Path(directory))
            print('Receipt extraction validated; returned field count:', len(result))
        if args.policy_file:
            def checked_callback(text, temperature=0.7, timeout=80):
                try:
                    return compile_policy_text(text, temperature, timeout)
                except LLMError as exc:
                    # Client messages are sanitized; do not print provider bodies or inputs.
                    print('Policy callback failed:', str(exc), file=sys.stderr)
                    raise
            configure_compiler(checked_callback)
            result = compile_policy(args.policy_file.read_text())
            print('Policy accepted by compiler checks:', result.policy is not None)
            print('Compiler flag codes:', ', '.join(flag.code for flag in result.flags) or 'none')
            if result.policy is None:
                return 1
        return 0
    except LLMError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print('Cannot read task input file.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
