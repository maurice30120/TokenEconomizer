"""File contracts over bytes captured by a complete, trustworthy observation."""
import hashlib
from pathlib import Path


def file_proof(root, path, observed, *, complete):
    """Build a proof only from a complete observation; never hash a later file read."""
    if not complete or not isinstance(observed, bytes):
        return None
    try:
        root = Path(root).resolve()
        target = (root / path).resolve()
        relative = target.relative_to(root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return {"path": str(relative), "sha256": hashlib.sha256(observed).hexdigest()}


def verify_file(root, proof):
    """Revalidate the stored observation, failing closed on unreadable files."""
    try:
        root = Path(root).resolve()
        target = (root / proof["path"]).resolve()
        target.relative_to(root)
        return hashlib.sha256(target.read_bytes()).hexdigest() == proof["sha256"]
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return False


# Only grammars whose declaration/name conventions are explicitly supported here.
LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript",
             ".ts": "typescript", ".tsx": "tsx", ".go": "go", ".rs": "rust",
             ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp"}
_DECLARATIONS = {"function_definition", "class_definition", "function_declaration",
                 "class_declaration", "method_definition", "method_declaration",
                 "function_item", "struct_item", "enum_item", "interface_declaration",
                 "type_declaration", "struct_specifier", "enum_specifier"}


def available_languages():
    """Return extensions whose configured parser can actually be loaded."""
    try:
        from tree_sitter_language_pack import get_parser
    except (ImportError, OSError):
        return {}
    available = {}
    for extension, language in LANGUAGES.items():
        try:
            get_parser(language)
            available[extension] = language
        except Exception:
            continue
    return available


def _symbol_hash(data, language, symbol):
    root_node = _parse(data, language)
    if root_node is None:
        return None
    matches = [node for node, name in _declarations(root_node, data) if name == symbol]
    if len(matches) != 1:
        return None
    return _node_hash(data, matches[0])


def _parse(data, language):
    """The parsed tree's root, or None when the file does not parse."""
    from tree_sitter_language_pack import get_parser
    tree = get_parser(language).parse(data)
    return None if tree.root_node.has_error else tree.root_node


def _declarations(root_node, data):
    """(node, name) per declaration in the tree, decorators included."""
    out = []
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type in _DECLARATIONS:
            name = node.child_by_field_name("name")
            if name is None and node.type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                while declarator and declarator.type != "identifier":
                    declarator = declarator.child_by_field_name("declarator")
                name = declarator
            if name:
                # Decorators belong to the declared symbol.
                out.append((node.parent if node.parent and node.parent.type == "decorated_definition"
                            else node, data[name.start_byte:name.end_byte].decode("utf-8", "replace")))
        stack.extend(node.children)
    return out


def _node_hash(data, node):
    """One symbol's footprint: its tokens, comments left out."""
    tokens = []
    stack = [node]
    while stack:
        node = stack.pop()
        if "comment" in node.type:
            continue
        if node.children:
            stack.extend(reversed(node.children))
        else:
            value = data[node.start_byte:node.end_byte]
            tokens.append(len(value).to_bytes(8, "big") + value)
    return hashlib.sha256(b"".join(tokens)).hexdigest()


def _proof(file, language, symbol, digest):
    from importlib.metadata import version
    return {"kind": "symbol", "path": file["path"], "symbol": symbol,
            "language": language, "grammar_version": version("tree-sitter-language-pack"),
            "runtime_version": version("tree-sitter"), "sha256": digest}


def _symbol_proof(file, data, language, symbol):
    digest = _symbol_hash(data, language, symbol)
    return None if digest is None else _proof(file, language, symbol, digest)


def symbol_proof(root, path, observed, symbol):
    """Create only an unambiguous proof over the observed version."""
    file = file_proof(root, path, observed, complete=True)
    language = LANGUAGES.get(Path(path).suffix.lower()) if isinstance(path, str) else None
    if not file or not language or not isinstance(symbol, str) or not symbol:
        return None
    try:
        return _symbol_proof(file, observed, language, symbol)
    except Exception:
        return None


def symbol_proofs_in(root, path, data, first_line, last_line):
    """Proofs, by name, over every declaration a read of these lines crossed.

    `data` is the file as the read returned it: the proof is over the WHOLE declaration in
    that version, comments excluded, so a later change anywhere in it -- read or not --
    invalidates the proof while a comment-only change does not. A name declared more than
    once in the file is ambiguous and proves nothing.
    """
    language = LANGUAGES.get(Path(path).suffix.lower()) if isinstance(path, str) else None
    file = file_proof(root, path, data, complete=True)
    if not language or not file:
        return {}
    try:
        lines = data.decode("utf-8").split("\n")
        if not 1 <= first_line <= last_line <= len(lines):
            return {}
        start = sum(len(line.encode("utf-8")) + 1 for line in lines[:first_line - 1])
        end = start + len("\n".join(lines[first_line - 1:last_line]).encode("utf-8"))
        root_node = _parse(data, language)
        if root_node is None:
            return {}
        declared = _declarations(root_node, data)
        names = [name for _, name in declared]
        out = {}
        for node, name in declared:
            if names.count(name) != 1 or node.start_byte >= end or node.end_byte <= start:
                continue
            try:
                out[name] = _proof(file, language, name, _node_hash(data, node))
            except Exception:
                continue
        return out
    except Exception:
        return {}


def verify_proof(root, proof):
    if not isinstance(proof, dict):
        return False
    if proof.get("kind") is None or proof.get("kind") == "file":
        return verify_file(root, proof)
    if proof.get("kind") != "symbol":
        return False
    try:
        root = Path(root).resolve()
        target = (root / proof["path"]).resolve()
        target.relative_to(root)
        current = symbol_proof(root, proof["path"], target.read_bytes(), proof["symbol"])
        return current == proof
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return False
