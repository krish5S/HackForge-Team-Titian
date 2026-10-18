"""Run on the configured OCR/GPU worker, not inside the web server.

Uses Dev 1 implementations unchanged. A directory lock prevents concurrent copies
of the same bundle; completed job outputs are reused on retries.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def run(directory):
    # Lazy imports keep the demo laptop's web app independent of pipeline/GPU packages.
    from backend.app.pipeline.process import process_receipt
    from backend.app.pipeline.duplicates import find_duplicates
    manifest = json.loads((directory / 'jobs.json').read_text())
    lock = directory / '.worker-lock'
    lock.mkdir()  # Fail rather than duplicate an already running worker.
    try:
        results, receipts = [], list(manifest['baseline_receipts'])
        for job in manifest['jobs']:
            cache = directory / f"{job['job_id']}.result.json"
            if cache.exists():
                result = json.loads(cache.read_text())
            else:
                source = (directory / job['image']).resolve()
                if not source.is_relative_to(directory.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != job['file_sha256']:
                    raise ValueError('Handoff source path/hash mismatch.')
                result = {key: job[key] for key in ('job_id', 'submission_id', 'file_sha256')}
                try:
                    payload = process_receipt(source, {'receipt_id': job['receipt_id']}, directory)
                    normalized = directory / f"{source.stem}_{job['file_sha256'][:12]}_normalized.jpg"
                    result.update(status='COMPLETED', receipt=payload,
                                  clean_file=normalized.name if normalized.is_file() else None)
                except Exception as exc:
                    print(f"Receipt processing failed ({type(exc).__name__}).", file=sys.stderr)
                    result.update(status='FAILED')
                temporary = cache.with_suffix('.tmp')
                temporary.write_text(json.dumps(result))
                temporary.replace(cache)
            results.append(result)
            if result['status'] == 'COMPLETED':
                receipts.append(result['receipt'])
        unique = {r['receipt_id']: r for r in receipts}
        texts = {}
        for rid, receipt in unique.items():
            cached_ocr = directory / 'ocr_cache' / f"{receipt['file_sha256']}.json"
            if cached_ocr.is_file():
                texts[rid] = json.loads(cached_ocr.read_text()).get('full_text', '')
        payload = {'results': results, 'duplicate_candidates': find_duplicates(list(unique.values()), texts)}
        temporary = directory / 'results.tmp'
        temporary.write_text(json.dumps(payload, indent=2))
        temporary.replace(directory / 'results.json')
    finally:
        lock.rmdir()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    run(args.directory.resolve())
