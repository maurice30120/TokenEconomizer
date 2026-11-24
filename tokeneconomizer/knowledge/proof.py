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
    from tree_sitter_language_pack import get_parser
    tree = get_parser(language).parse(data)
    if tree.root_node.has_error:
        return None
    matches = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in _DECLARATIONS:
            name = node.child_by_field_name("name")
            if name is None and node.type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                while declarator and declarator.type != "identifier":
                    declarator = declarator.child_by_field_name("declarator")
                name = declarator
            if name and data[name.start_byte:name.end_byte].decode("utf-8") == symbol:
                # Decorators belong to the declared symbol.
                matches.append(node.parent if node.parent and node.parent.type == "decorated_definition" else node)
        stack.extend(node.children)
    if len(matches) != 1:
        return None
    tokens = []
    stack = [matches[0]]
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


def symbol_proof(root, path, observed, symbol):
    """Create only an unambiguous proof over the observed version."""
    from importlib.metadata import version
    file = file_proof(root, path, observed, complete=True)
    language = LANGUAGES.get(Path(path).suffix.lower()) if isinstance(path, str) else None
    if not file or not language or not isinstance(symbol, str) or not symbol:
        return None
    try:
        digest = _symbol_hash(observed, language, symbol)
        if digest is None:
            return None
        return {"kind": "symbol", "path": file["path"], "symbol": symbol,
                "language": language, "grammar_version": version("tree-sitter-language-pack"),
                "runtime_version": version("tree-sitter"),
                "sha256": digest}
    except Exception:
        return None


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
