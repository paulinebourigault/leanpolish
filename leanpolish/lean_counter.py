"""Python port of `countLeanTokens` from LeanPolish.lean.

This is the token counter that produces the per-file `tokens_original` /
`tokens_shortened` report fields and the primary token metrics. It skips
comments and treats ASCII alphanumerics, `_`, `'` and subscript digits as
identifier characters.

Usage (as a library):
    from lean_counter import count_lean_tokens
"""
def _ident(c):
    return ('a' <= c <= 'z') or ('A' <= c <= 'Z') or ('0' <= c <= '9') or c in "_'" or 0x2080 <= ord(c) <= 0x2089
OPS2 = {":=", "!=", "->", "<-", "=>", ">=", "<=", "++", ">>", "..", "#["}
def count_lean_tokens(s):
    n, i, L = 0, 0, len(s)
    while i < L:
        c = s[i]
        if c in ' \t\n\r': i += 1; continue
        if c == '-' and i + 1 < L and s[i+1] == '-':
            i += 2
            while i < L and s[i] != '\n': i += 1
            continue
        if c == '/' and i + 1 < L and s[i+1] == '-':
            i += 2; d = 1
            while i < L and d > 0:
                if s[i] == '/' and i + 1 < L and s[i+1] == '-': d += 1; i += 2
                elif s[i] == '-' and i + 1 < L and s[i+1] == '/': d -= 1; i += 2
                else: i += 1
            continue
        if _ident(c):
            i += 1
            while i < L and _ident(s[i]): i += 1
            n += 1; continue
        if i + 2 < L and s[i:i+3] in ("<;>", ">>="): n += 1; i += 3; continue
        if i + 1 < L and s[i:i+2] in OPS2: n += 1; i += 2; continue
        n += 1; i += 1
    return n
