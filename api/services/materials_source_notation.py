"""Read-only, bounded expansion of literal macros from a pinned paper source.

No files, shell, assignments or conditionals are executed. Ambiguous
definitions are rejected. Exact definitions and member hashes are retained.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

COMMAND = re.compile(r'\\[A-Za-z@]+|\\.')
DEFINITION = re.compile(r'\\(newcommand|renewcommand|providecommand|DeclareRobustCommand)\*?|\\(def|gdef)(?![A-Za-z])')
UNSAFE = re.compile(r'\\(?:input|include|write|read|openin|openout|catcode|csname|expandafter|edef|xdef|def|gdef|let|newcommand|renewcommand|if[a-zA-Z]*|else|fi|loop|repeat|special|href|url|html[a-zA-Z]*)(?![A-Za-z])')


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def uncomment(text: str) -> str:
    return re.sub(r'(?<!\\)%[^\n]*', '', text)


def argument(text: str, pos: int) -> tuple[str, int]:
    """A TeX argument is a balanced group or a single token, not a word."""
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        raise ValueError('Missing macro argument')
    if text[pos] != '{':
        match = COMMAND.match(text, pos)
        end = match.end() if match else pos + 1
        return text[pos:end], end
    depth, start = 1, pos + 1
    pos += 1
    while pos < len(text):
        if text[pos] == '\\':
            match = COMMAND.match(text, pos)
            pos = match.end() if match else pos + 1
            continue
        depth += (text[pos] == '{') - (text[pos] == '}')
        if depth == 0:
            return text[start:pos], pos + 1
        pos += 1
    raise ValueError('Unbalanced macro argument')


@dataclass(frozen=True)
class Macro:
    name: str
    nargs: int
    body: str
    locator: str
    member_sha256: str
    definition: str
    suffix: str = ''


def global_literal_context(source: str, position: int) -> bool:
    # Definitions inside a local group or an unevaluated conditional must not
    # be promoted to a document-wide material name. New-if declarations do not
    # open a conditional. This intentionally rejects unsupported TeX contexts.
    prefix=re.sub(r'\\newif\s*\\if[A-Za-z@]+', '', source[:position])
    braces=conditionals=groups=0
    for token in re.findall(r'\\[A-Za-z@]+|\\.|[{}]',prefix):
        if token=='{':braces+=1
        elif token=='}':braces-=1
        elif token.startswith(r'\if'):conditionals+=1
        elif token==r'\fi':conditionals-=1
        elif token==r'\begingroup':groups+=1
        elif token==r'\endgroup':groups-=1
    return braces==conditionals==groups==0


def definitions(blocks: list[dict]) -> dict[str, Macro]:
    found = defaultdict(list)
    for block in blocks:
        source = uncomment(block['text'])
        for match in DEFINITION.finditer(source):
            if not global_literal_context(source,match.start()):
                continue
            try:
                name, pos = argument(source, match.end())
                if not re.fullmatch(r'\\(?:[A-Za-z@]+|[0-9])', name):
                    continue
                nargs = 0; suffix = ''
                while pos < len(source) and source[pos].isspace():
                    pos += 1
                if match[1] and source[pos:pos+1] == '[':
                    count = re.match(r'\[([0-9])\]', source[pos:])
                    if not count:
                        continue
                    nargs = int(count[1]); pos += len(count[0])
                elif match[2]:
                    params = re.match(r'(?:#[1-9])*', source[pos:])[0]
                    nargs = len(params) // 2
                    if params != ''.join(f'#{i}' for i in range(1, nargs+1)):
                        continue
                    pos += len(params)
                    if not params:
                        suffix = re.match(r'[A-Za-z0-9()\-]*', source[pos:])[0]
                        pos += len(suffix)
                while pos < len(source) and source[pos].isspace():
                    pos += 1
                # Optional/default arguments and delimited definitions are not
                # part of this safe subset. Neither are arbitrary token bodies.
                if source[pos:pos+1] != '{':
                    continue
                body, end = argument(source, pos)
                definition = source[match.start():end]
                if len(body) > 2048 or UNSAFE.search(body) or re.search(r'#(?![1-9])', body):
                    continue
                if any(int(i) > nargs for i in re.findall(r'#([1-9])', body)):
                    continue
                found[name].append(Macro(name,nargs,body,block['locator'],
                    block['sha256'],definition,suffix))
            except (ValueError, IndexError):
                continue
    # Conflicts across archive members or redefinitions are not resolved by
    # arbitrary file order. Macros from a different paper are never consulted.
    return {name: items[0] for name, items in found.items()
            if len({(m.nargs,m.body,m.suffix) for m in items}) == 1}


def expand(value: str, macros: dict[str, Macro]) -> tuple[str, list[dict]]:
    used = {}
    budget = [128]
    def walk(text, stack=()):
        if len(text) > 32768 or len(stack) > 16:
            raise ValueError('Macro expansion limit')
        result, pos = [], 0
        while match := COMMAND.search(text, pos):
            result.append(text[pos:match.start()])
            name = match[0]
            macro = macros.get(name)
            if not macro:
                result.append(name + (' ' if name[-1].isalpha() else '')); pos=match.end(); continue
            if name in stack or budget[0] <= 0:
                raise ValueError('Recursive macro')
            pos = match.end(); args=[]
            if macro.suffix:
                if not text.startswith(macro.suffix,pos):
                    result.append(name+' ');continue
                pos += len(macro.suffix)
            for _ in range(macro.nargs):
                arg,pos=argument(text,pos);args.append(arg)
            body=re.sub(r'#([1-9])',lambda m:args[int(m[1])-1],macro.body)
            used[name]=dict(command=name,locator=macro.locator,
                member_sha256=macro.member_sha256,definition=macro.definition)
            budget[0]-=1
            result.append(walk(body,(*stack,name)))
        result.append(text[pos:])
        joined=''.join(result)
        if len(joined)>32768:
            raise ValueError('Macro expansion limit')
        return joined
    try:
        resolved=walk(value)
        return (resolved,sorted(used.values(),key=lambda x:x['command'])) if used else (value,[])
    except ValueError:
        return value,[]
