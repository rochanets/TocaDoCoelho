#!/usr/bin/env python3
"""Falha a CI quando artefatos sensíveis ou credenciais prováveis são rastreados."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNED_PREFIXES = (
    'app.py',
    'routes/',
    'integrations/',
    'deploy/',
    'scripts/',
    '.github/workflows/',
    'Dockerfile',
    'docker-compose',
    '.env.production.example',
)
FORBIDDEN_SUFFIXES = (
    '.pem',
    '.key',
    '.p12',
    '.pfx',
    '.dump',
    '.db',
    '.sqlite',
)
ALLOWED_FIXTURE_FILES = {
    'BD_teste/toca-do-coelho-ficticio-reduzido.db',
}
TOKEN_PATTERNS = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'slack_token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    'openai_key': re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b'),
}
LITERAL_ASSIGNMENT = re.compile(
    r'''(?ix)
    \b([a-z0-9_-]*(?:password|secret(?:[_-]?key)?|token|api[_-]?key)[a-z0-9_-]*)\b
    \s*[:=]\s*
    ["']([^"'{}\r\n]{16,})["']
    '''
)
ENV_LITERAL_ASSIGNMENT = re.compile(
    r'''(?mx)
    ^\s*([A-Z0-9_-]*(?:PASSWORD|SECRET(?:[_-]?KEY)?|TOKEN|API[_-]?KEY)[A-Z0-9_-]*)
    \s*=\s*([^\s#"'{}$]{16,})\s*$
    '''
)
ALLOWED_LITERAL_MARKERS = (
    'replace_me',
    'change_me',
    'example',
    'placeholder',
    'ci-only',
    'disposable',
    'fake',
    'dummy',
    'test',
    '[redacted]',
)


def tracked_files():
    output = subprocess.check_output(
        ['git', 'ls-files', '-z'],
        cwd=ROOT,
    )
    return [
        item.decode('utf-8')
        for item in output.split(b'\0')
        if item
    ]


def should_scan(path):
    return path.startswith(SCANNED_PREFIXES)


def scan():
    findings = []
    for relative in tracked_files():
        normalized = relative.replace('\\', '/')
        lowered = normalized.lower()
        if normalized in ALLOWED_FIXTURE_FILES:
            continue
        if (
            lowered == '.env'
            or (lowered.startswith('.env.') and lowered != '.env.production.example')
            or '/.waha/' in f'/{lowered}/'
            or lowered.endswith(FORBIDDEN_SUFFIXES)
        ):
            findings.append(f'{normalized}: arquivo sensível rastreado')
            continue
        if not should_scan(normalized):
            continue
        path = ROOT / relative
        try:
            content = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in TOKEN_PATTERNS.items():
            for match in pattern.finditer(content):
                line = content.count('\n', 0, match.start()) + 1
                findings.append(f'{normalized}:{line}: padrão {name}')
        for match in LITERAL_ASSIGNMENT.finditer(content):
            value = match.group(2).strip().lower()
            if any(marker in value for marker in ALLOWED_LITERAL_MARKERS):
                continue
            line = content.count('\n', 0, match.start()) + 1
            findings.append(
                f'{normalized}:{line}: literal provável em {match.group(1)}'
            )
        for match in ENV_LITERAL_ASSIGNMENT.finditer(content):
            value = match.group(2).strip().lower()
            if any(marker in value for marker in ALLOWED_LITERAL_MARKERS):
                continue
            line = content.count('\n', 0, match.start()) + 1
            findings.append(
                f'{normalized}:{line}: literal provável em {match.group(1)}'
            )
    return findings


def main():
    findings = scan()
    if findings:
        print('Possíveis segredos/artefatos sensíveis rastreados:', file=sys.stderr)
        for finding in findings:
            print(f'- {finding}', file=sys.stderr)
        return 1
    print('secret_scan_ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
