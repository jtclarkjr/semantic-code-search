use crate::bundle::{DocumentKind, SourceChunk, SourceDocument};
use anyhow::Result;
use tree_sitter::{Language, Parser};

#[derive(Debug, Clone)]
struct Block {
    content: String,
    start_line: usize,
    end_line: usize,
}

#[derive(Debug, Clone)]
pub struct ChunkingService {
    pub max_chars: usize,
    pub overlap_chars: usize,
}

impl Default for ChunkingService {
    fn default() -> Self {
        Self {
            max_chars: 1800,
            overlap_chars: 200,
        }
    }
}

impl ChunkingService {
    pub fn chunk_documents(&self, documents: &[SourceDocument]) -> Vec<SourceChunk> {
        documents
            .iter()
            .flat_map(|document| self.chunk_document(document))
            .collect()
    }

    pub fn chunk_document(&self, document: &SourceDocument) -> Vec<SourceChunk> {
        match document.kind {
            DocumentKind::Commit => self.chunk_commit_document(document),
            DocumentKind::Documentation => self.chunk_text_document(document),
            DocumentKind::Code => self.chunk_code_document(document),
        }
    }

    fn chunk_code_document(&self, document: &SourceDocument) -> Vec<SourceChunk> {
        let mut blocks = self.tree_sitter_blocks(document).unwrap_or_default();
        if blocks.is_empty() {
            blocks = self.heuristic_code_blocks(&document.content, document.language.as_deref());
        }
        if blocks.is_empty() {
            blocks.push(Block {
                content: document.content.clone(),
                start_line: 1,
                end_line: line_count(&document.content),
            });
        }
        self.materialize_blocks(document, blocks)
    }

    fn chunk_text_document(&self, document: &SourceDocument) -> Vec<SourceChunk> {
        let blocks = split_paragraph_blocks(&document.content);
        let blocks = if blocks.is_empty() {
            vec![Block {
                content: document.content.clone(),
                start_line: 1,
                end_line: line_count(&document.content),
            }]
        } else {
            blocks
        };
        self.materialize_blocks(document, blocks)
    }

    fn chunk_commit_document(&self, document: &SourceDocument) -> Vec<SourceChunk> {
        self.materialize_blocks(
            document,
            vec![Block {
                content: document.content.clone(),
                start_line: 1,
                end_line: line_count(&document.content),
            }],
        )
    }

    fn materialize_blocks(
        &self,
        document: &SourceDocument,
        blocks: Vec<Block>,
    ) -> Vec<SourceChunk> {
        let mut chunks = Vec::new();
        for block in blocks {
            for piece in self.split_large_block(&block) {
                let mut chunk = SourceChunk::new(
                    document.document_id.clone(),
                    document.kind.clone(),
                    document.path.clone(),
                    piece.content.clone(),
                );
                chunk.preview = preview(&piece.content);
                chunk.start_line = piece.start_line as i32;
                chunk.end_line = piece.end_line as i32;
                chunk.language = document.language.clone();
                chunk.commit_sha = document.commit_sha.clone();
                chunk.metadata = document.metadata.clone();
                chunks.push(chunk);
            }
        }
        chunks
    }

    fn split_large_block(&self, block: &Block) -> Vec<Block> {
        if block.content.chars().count() <= self.max_chars {
            return vec![block.clone()];
        }

        let lines: Vec<&str> = block.content.lines().collect();
        let mut pieces = Vec::new();
        let mut current: Vec<String> = Vec::new();
        let mut current_start = block.start_line;
        let mut current_chars = 0usize;

        for (offset, line) in lines.iter().enumerate() {
            let line_len = line.chars().count() + 1;
            if !current.is_empty() && current_chars + line_len > self.max_chars {
                let content = current.join("\n").trim().to_string();
                let end_line = current_start + current.len().saturating_sub(1);
                pieces.push(Block {
                    content,
                    start_line: current_start,
                    end_line,
                });

                let overlap = tail_with_overlap(&current, self.overlap_chars);
                current = overlap;
                current_start = end_line.saturating_sub(current.len()).saturating_add(2);
                current_chars = current.iter().map(|item| item.chars().count() + 1).sum();
            }

            current.push((*line).to_string());
            current_chars += line_len;

            if offset == lines.len().saturating_sub(1) && !current.is_empty() {
                let content = current.join("\n").trim().to_string();
                let end_line = current_start + current.len().saturating_sub(1);
                pieces.push(Block {
                    content,
                    start_line: current_start,
                    end_line,
                });
            }
        }

        pieces
    }

    fn tree_sitter_blocks(&self, document: &SourceDocument) -> Result<Vec<Block>> {
        let language_name = match document.language.as_deref() {
            Some("python") | Some("javascript") | Some("typescript") => {
                document.language.as_deref().unwrap()
            }
            _ => return Ok(Vec::new()),
        };
        let language = parser_language(language_name)
            .ok_or_else(|| anyhow::anyhow!("unsupported language"))?;
        let mut parser = Parser::new();
        parser
            .set_language(&language)
            .map_err(|error| anyhow::anyhow!("failed to configure parser: {error}"))?;
        let tree = parser
            .parse(document.content.as_str(), None)
            .ok_or_else(|| anyhow::anyhow!("tree-sitter parse failed"))?;
        let root = tree.root_node();
        let lines: Vec<&str> = document.content.lines().collect();
        let mut cursor = root.walk();
        let mut blocks = Vec::new();

        for child in root.named_children(&mut cursor) {
            let mut node = child;
            if node.kind() == "export_statement" {
                if let Some(named) = node.named_child(0) {
                    node = named;
                }
            }
            if !is_wanted_node(language_name, node.kind()) {
                continue;
            }
            let start_line = node.start_position().row + 1;
            let end_line = node.end_position().row + 1;
            let snippet = lines
                .get(start_line.saturating_sub(1)..end_line)
                .unwrap_or(&[])
                .join("\n")
                .trim()
                .to_string();
            if !snippet.is_empty() {
                blocks.push(Block {
                    content: snippet,
                    start_line,
                    end_line,
                });
            }
        }

        Ok(blocks)
    }

    fn heuristic_code_blocks(&self, content: &str, language: Option<&str>) -> Vec<Block> {
        let lines: Vec<&str> = content.lines().collect();
        let mut starts = Vec::new();

        for (idx, line) in lines.iter().enumerate() {
            let trimmed = line.trim();
            let is_start = match language {
                Some("python") => {
                    trimmed.starts_with("class ")
                        || trimmed.starts_with("async def ")
                        || trimmed.starts_with("def ")
                }
                Some("javascript") | Some("typescript") | Some("vue") => {
                    trimmed.starts_with("export default")
                        || trimmed.starts_with("export async function ")
                        || trimmed.starts_with("export function ")
                        || trimmed.starts_with("async function ")
                        || trimmed.starts_with("function ")
                        || trimmed.starts_with("export const ")
                        || trimmed.starts_with("const ")
                        || trimmed.starts_with("class ")
                }
                _ => false,
            };
            if is_start {
                starts.push(idx);
            }
        }

        if starts.is_empty() {
            return Vec::new();
        }
        starts.push(lines.len());

        let mut blocks = Vec::new();
        for pair in starts.windows(2) {
            let start = pair[0];
            let end = pair[1];
            let snippet = lines[start..end].join("\n").trim().to_string();
            if !snippet.is_empty() {
                blocks.push(Block {
                    content: snippet,
                    start_line: start + 1,
                    end_line: end.max(start + 1),
                });
            }
        }
        blocks
    }
}

fn line_count(content: &str) -> usize {
    content.lines().count().max(1)
}

fn preview(content: &str) -> String {
    let lines: Vec<&str> = content.lines().take(12).collect();
    let preview = lines.join("\n").trim().to_string();
    if preview.is_empty() {
        content.chars().take(240).collect()
    } else {
        preview
    }
}

fn tail_with_overlap(lines: &[String], overlap_chars: usize) -> Vec<String> {
    let mut overlap = Vec::new();
    let mut total = 0usize;
    for line in lines.iter().rev() {
        total += line.chars().count() + 1;
        overlap.insert(0, line.clone());
        if total >= overlap_chars {
            break;
        }
    }
    overlap
}

fn split_paragraph_blocks(content: &str) -> Vec<Block> {
    let mut blocks = Vec::new();
    let mut current = Vec::new();
    let mut current_start = 1usize;

    for (index, line) in content.lines().enumerate() {
        if line.trim().is_empty() {
            if !current.is_empty() {
                let end_line = current_start + current.len().saturating_sub(1);
                blocks.push(Block {
                    content: current.join("\n").trim().to_string(),
                    start_line: current_start,
                    end_line,
                });
                current.clear();
            }
            current_start = index + 2;
            continue;
        }

        if current.is_empty() {
            current_start = index + 1;
        }
        current.push(line.to_string());
    }

    if !current.is_empty() {
        let end_line = current_start + current.len().saturating_sub(1);
        blocks.push(Block {
            content: current.join("\n").trim().to_string(),
            start_line: current_start,
            end_line,
        });
    }

    blocks
}

fn parser_language(language: &str) -> Option<Language> {
    match language {
        "python" => Some(tree_sitter_python::LANGUAGE.into()),
        "javascript" => Some(tree_sitter_javascript::LANGUAGE.into()),
        "typescript" => Some(tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()),
        _ => None,
    }
}

fn is_wanted_node(language: &str, kind: &str) -> bool {
    match language {
        "python" => matches!(kind, "class_definition" | "function_definition"),
        "javascript" => matches!(
            kind,
            "class_declaration"
                | "function_declaration"
                | "generator_function_declaration"
                | "lexical_declaration"
                | "variable_declaration"
        ),
        "typescript" => matches!(
            kind,
            "class_declaration"
                | "function_declaration"
                | "generator_function_declaration"
                | "lexical_declaration"
                | "variable_declaration"
                | "interface_declaration"
                | "type_alias_declaration"
        ),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bundle::{DocumentKind, SourceDocument};
    use serde_json::Map;

    fn source_document(path: &str, language: Option<&str>, content: &str) -> SourceDocument {
        SourceDocument {
            document_id: "doc-1".to_string(),
            kind: DocumentKind::Code,
            path: path.to_string(),
            content: content.to_string(),
            title: None,
            language: language.map(str::to_string),
            external_id: None,
            commit_sha: None,
            metadata: Map::new(),
        }
    }

    #[test]
    fn chunks_python_functions() {
        let service = ChunkingService::default();
        let document = source_document(
            "main.py",
            Some("python"),
            "def alpha():\n    return 1\n\nclass Beta:\n    pass\n",
        );

        let chunks = service.chunk_document(&document);

        assert!(chunks
            .iter()
            .any(|chunk| chunk.content.contains("def alpha")));
        assert!(chunks
            .iter()
            .any(|chunk| chunk.content.contains("class Beta")));
    }
}
