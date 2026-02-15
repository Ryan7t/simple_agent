"""
文档加载器模块
负责解析文案目录下的 docx 文件
"""
import os
import glob
from docx import Document
from colorama import Fore, Style
from typing import Optional


class DocxLoader:
    """Docx 文档加载器"""

    def __init__(self, documents_dir: str):
        self.documents_dir = documents_dir
        self._content = None
        self._last_modified: Optional[float] = None  # 记录最后修改时间

    def load(self) -> str:
        """
        加载并解析所有 docx 文件

        Returns:
            所有文档的文本内容
        """
        # 检查文件修改时间
        current_mtime = self._get_documents_mtime()
        if self._content is not None and current_mtime == self._last_modified:
            return self._content

        context_text = ""

        if not os.path.exists(self.documents_dir):
            self._content = ""
            self._last_modified = current_mtime
            return ""

        docx_files = glob.glob(os.path.join(self.documents_dir, "*.docx"))

        if not docx_files:
            self._content = ""
            self._last_modified = current_mtime
            return ""

        for file_path in docx_files:
            try:
                doc = Document(file_path)
                file_content = []
                for para in doc.paragraphs:
                    if para.text.strip():
                        file_content.append(para.text.strip())

                if file_content:
                    filename = os.path.basename(file_path)
                    context_text += f"\n\n--- 文件名：{filename} ---\n"
                    context_text += "\n".join(file_content)
            except Exception as e:
                print(f"{Fore.YELLOW}无法读取文件 {file_path}: {e}{Style.RESET_ALL}")

        self._content = context_text
        self._last_modified = current_mtime  # 更新最后修改时间
        return self._content

    def reload(self) -> str:
        """强制重新加载文档"""
        self._content = None
        return self.load()

    def get_file_count(self) -> int:
        """获取文档数量"""
        if not os.path.exists(self.documents_dir):
            return 0
        return len(glob.glob(os.path.join(self.documents_dir, "*.docx")))

    def _get_documents_mtime(self) -> Optional[float]:
        """获取文档目录中所有文件的综合修改时间"""
        if not os.path.exists(self.documents_dir):
            return None
        docx_files = glob.glob(os.path.join(self.documents_dir, "*.docx"))
        if not docx_files:
            return None
        # 返回最新文件的修改时间
        return max(os.path.getmtime(f) for f in docx_files)
