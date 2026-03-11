from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from common.schemas import SourceChunk, SourceDocument

try:
    from tree_sitter_languages import get_parser
except ImportError:  # pragma: no cover - exercised when optional parser package is missing
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        try:
            from dom_tree_sitter_language_pack import get_parser
        except ImportError:
            get_parser = None


class ChunkingService:
    def __init__(self, max_chars: int = 1800, overlap_chars: int = 200) -> None:
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_documents(self, documents: Sequence[SourceDocument]) -> List[SourceChunk]:
        chunks: List[SourceChunk] = []
        for document in documents:
            chunks.extend(self.chunk_document(document))
        return chunks

    def chunk_document(self, document: SourceDocument) -> List[SourceChunk]:
        if document.kind == "commit":
            return self._chunk_text_document(document, paragraph_mode=False)
        if document.kind == "documentation":
            return self._chunk_text_document(document, paragraph_mode=True)
        return self._chunk_code_document(document)

    def _chunk_code_document(self, document: SourceDocument) -> List[SourceChunk]:
        blocks = self._tree_sitter_blocks(document)
        if not blocks:
            blocks = self._heuristic_code_blocks(document.content, document.language)
        if not blocks:
            blocks = [(document.content, 1, max(document.content.count("\n") + 1, 1))]
        return self._materialize_blocks(document, blocks)

    def _chunk_text_document(
        self,
        document: SourceDocument,
        paragraph_mode: bool,
    ) -> List[SourceChunk]:
        if paragraph_mode:
            raw_blocks = re.split(r"\n\s*\n", document.content.strip())
        else:
            raw_blocks = [
                block.strip() for block in document.content.split("\x1e") if block.strip()
            ]

        if not raw_blocks:
            raw_blocks = [document.content]

        blocks: List[Tuple[str, int, int]] = []
        running_line = 1
        for block in raw_blocks:
            block_lines = block.splitlines() or [block]
            line_count = len(block_lines)
            blocks.append((block.strip(), running_line, running_line + line_count - 1))
            running_line += line_count + 1
        return self._materialize_blocks(document, blocks)

    def _materialize_blocks(
        self,
        document: SourceDocument,
        blocks: Iterable[Tuple[str, int, int]],
    ) -> List[SourceChunk]:
        chunks: List[SourceChunk] = []
        for block, start_line, end_line in blocks:
            for piece, piece_start, piece_end in self._split_large_block(block, start_line):
                preview = "\n".join(piece.splitlines()[:12]).strip() or piece[:240]
                chunks.append(
                    SourceChunk(
                        document_id=document.document_id,
                        kind=document.kind,
                        path=document.path,
                        content=piece,
                        preview=preview,
                        start_line=piece_start,
                        end_line=min(piece_end, end_line),
                        language=document.language,
                        commit_sha=document.commit_sha,
                        metadata=document.metadata.copy(),
                    )
                )
        return chunks

    def _split_large_block(self, block: str, start_line: int) -> List[Tuple[str, int, int]]:
        if len(block) <= self.max_chars:
            line_count = max(block.count("\n") + 1, 1)
            return [(block.strip(), start_line, start_line + line_count - 1)]

        pieces: List[Tuple[str, int, int]] = []
        lines = block.splitlines()
        current: List[str] = []
        current_start = start_line
        current_chars = 0

        for index, line in enumerate(lines, start=start_line):
            line_len = len(line) + 1
            if current and current_chars + line_len > self.max_chars:
                piece = "\n".join(current).strip()
                piece_end = current_start + len(current) - 1
                pieces.append((piece, current_start, piece_end))
                overlap_lines = self._tail_with_overlap(current)
                current = overlap_lines[:]
                current_start = piece_end - len(overlap_lines) + 2
                current_chars = sum(len(item) + 1 for item in current)

            current.append(line)
            current_chars += line_len

        if current:
            piece = "\n".join(current).strip()
            piece_end = current_start + len(current) - 1
            pieces.append((piece, current_start, piece_end))
        return pieces

    def _tail_with_overlap(self, lines: Sequence[str]) -> List[str]:
        overlap: List[str] = []
        total = 0
        for line in reversed(lines):
            total += len(line) + 1
            overlap.insert(0, line)
            if total >= self.overlap_chars:
                break
        return overlap

    def _tree_sitter_blocks(self, document: SourceDocument) -> List[Tuple[str, int, int]]:
        if get_parser is None or document.language not in {"python", "javascript", "typescript"}:
            return []
        parser_language = document.language
        try:
            parser = get_parser(parser_language)
            tree = parser.parse(bytes(document.content, "utf-8"))
        except Exception:
            return []

        wanted_types = {
            "python": {"class_definition", "function_definition"},
            "javascript": {
                "class_declaration",
                "function_declaration",
                "generator_function_declaration",
                "lexical_declaration",
                "variable_declaration",
            },
            "typescript": {
                "class_declaration",
                "function_declaration",
                "generator_function_declaration",
                "lexical_declaration",
                "variable_declaration",
                "interface_declaration",
                "type_alias_declaration",
            },
        }[document.language]

        blocks: List[Tuple[str, int, int]] = []
        for child in getattr(tree.root_node, "children", []):
            node = child
            if node.type == "export_statement" and getattr(node, "named_children", None):
                node = node.named_children[0]
            if node.type not in wanted_types:
                continue
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            lines = document.content.splitlines()
            snippet = "\n".join(lines[start_line - 1 : end_line]).strip()
            if snippet:
                blocks.append((snippet, start_line, end_line))
        return blocks

    def _heuristic_code_blocks(
        self,
        content: str,
        language: Optional[str],
    ) -> List[Tuple[str, int, int]]:
        if language == "python":
            return self._split_on_patterns(
                content, [r"^class\s+\w+", r"^async\s+def\s+\w+", r"^def\s+\w+"]
            )
        if language in {"javascript", "typescript", "vue"}:
            return self._split_on_patterns(
                content,
                [
                    r"^export\s+default",
                    r"^export\s+(async\s+)?function\s+\w+",
                    r"^(async\s+)?function\s+\w+",
                    r"^export\s+const\s+\w+",
                    r"^const\s+\w+\s*=",
                    r"^class\s+\w+",
                ],
            )
        return []

    def _split_on_patterns(
        self, content: str, patterns: Sequence[str]
    ) -> List[Tuple[str, int, int]]:
        compiled = [re.compile(pattern) for pattern in patterns]
        lines = content.splitlines()
        starts: List[int] = []
        for idx, line in enumerate(lines):
            if any(pattern.search(line.strip()) for pattern in compiled):
                starts.append(idx)
        if not starts:
            return []
        starts.append(len(lines))
        blocks: List[Tuple[str, int, int]] = []
        for current, nxt in zip(starts, starts[1:]):
            snippet = "\n".join(lines[current:nxt]).strip()
            if snippet:
                blocks.append((snippet, current + 1, nxt))
        return blocks
