"""File handler for the uploads/ directory — read and ingest user-provided files"""
import os
from pathlib import Path
from typing import Dict, List, Optional

UPLOADS_DIR = Path(__file__).parent.parent / "uploads"

# File types we can read as plain text
SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.rst', '.csv', '.json', '.jsonl',
    '.py', '.js', '.ts', '.sh', '.bash', '.zsh',
    '.yaml', '.yml', '.toml', '.ini', '.cfg', '.env',
    '.log', '.html', '.xml', '.sql', '.r', '.go',
    '.java', '.c', '.cpp', '.h', '.cs', '.rb', '.php',
}

_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB


class FileHandler:
    def __init__(self):
        UPLOADS_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def list_files(self) -> List[Dict]:
        """Return metadata for every file in the uploads directory."""
        files = []
        try:
            for f in sorted(UPLOADS_DIR.iterdir()):
                if f.is_file() and not f.name.startswith('.'):
                    stat = f.stat()
                    files.append({
                        'name': f.name,
                        'size': stat.st_size,
                        'extension': f.suffix.lower(),
                        'supported': f.suffix.lower() in SUPPORTED_EXTENSIONS,
                    })
        except Exception:
            pass
        return files

    # ------------------------------------------------------------------
    # File reading
    # ------------------------------------------------------------------

    def _resolve_safe(self, filename: str) -> Optional[Path]:
        """Return the resolved Path only if it sits inside UPLOADS_DIR."""
        path = (UPLOADS_DIR / filename).resolve()
        if not str(path).startswith(str(UPLOADS_DIR.resolve())):
            return None  # path-traversal attempt
        return path if path.exists() and path.is_file() else None

    def read_file(self, filename: str) -> Optional[str]:
        """Read and return file contents as a string, or None on failure."""
        path = self._resolve_safe(filename)
        if path is None:
            return None
        if path.stat().st_size > _SIZE_LIMIT:
            return None  # too large
        try:
            return path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Ingestion into RAG
    # ------------------------------------------------------------------

    async def ingest_file(self, filename: str, rag_retriever) -> bool:
        """Read *filename* from uploads/ and embed it into FAISS."""
        path = self._resolve_safe(filename)
        if path is None:
            return False
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False

        content = self.read_file(filename)
        if not content or not content.strip():
            return False

        doc_id = await rag_retriever.add_document(
            content=content,
            title=filename,
            url=f"file://uploads/{filename}",
            metadata={'type': 'upload', 'filename': filename},
        )
        return doc_id is not None

    async def ingest_all(self, rag_retriever) -> Dict:
        """Ingest every supported file in uploads/. Returns a results dict."""
        results: Dict[str, List[str]] = {'success': [], 'failed': [], 'skipped': []}
        for f in self.list_files():
            if not f['supported']:
                results['skipped'].append(f['name'])
                continue
            ok = await self.ingest_file(f['name'], rag_retriever)
            if ok:
                results['success'].append(f['name'])
            else:
                results['failed'].append(f['name'])
        return results


file_handler = FileHandler()
